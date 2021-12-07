# Quickstart (from example.py in the repo)
NOTE: This is a work-in-progress, the code is not ready for production use.  

 ```python
  from ftx.client import Client
  from ftx.websocket import Websocket
  from ftx.orderbook_feed import OrderBookFeed
  import time
 
  ###########################
  ## REST Client
  ###########################
 
  API_KEY = None # provide your key here
  client = Client(api_key=API_KEY)

  # get active contracts
  print('Getting active contracts...')
  time.sleep(2)

  active_contracts = client.list_contracts(active=True)
  num_active = len(active_contracts['data'])
  print('Number of active contracts: {}'.format(num_active))
  print()
  time.sleep(2)

  ###########################
  ## Websocket
  ###########################

  ## For lower-level control: use this when you want to receive every single message

  class MyWebSocket(Websocket):
      def on_open(self,ws):
          print('connected to {}'.format(self.url))

      def on_message(self,ws,msg):
          print('received msg: {}'.format(msg))

      def on_close(self,ws,close_status_cd,msg):
          print('closed connection to {}'.format(self.url))

      def on_error(self,ws,errmsg):
          print('error: {}'.format(errmsg))

  print('Printing all websocket messages...')
  time.sleep(2)

  ws = MyWebSocket(api_key=API_KEY)
  ws.start()

  ## listen for 2 seconds and then stop
  time.sleep(2)
  ws.stop()
  time.sleep(2)
  print()
  ###########################
  ## Real-Time Orderbook
  ###########################

  ## For higher-level control: use this when you want to track book state 
  ## of one or more products.

  ## takes an `on_book` function which will be called when any of the
  ## orderbooks that have been subscribed to are updated.  

  ## IMPORTANT: 
  ## This function is called in the thread listening to websocket messages,
  ## so if you block on this call, you will block the websocket and all 
  ## subsequent messages.  In otherwords, don't do IO in this function, get
  ## in and get out.
  def do_something_with_book(book):
      print(book)

  books = OrderBookFeed(
      api_key=API_KEY,
      contracts=[22229264, 22209160, 22229265,22229263,22229262],
      on_book=do_something_with_book        
  )

  print('Displaying orderbook updates...')
  time.sleep(2)

  books.start()

  ## Listen for 5 seconds then stop. 

  ## Note: if none of the books subscribed to update during this time you won't
  ## see anything print.  Increase the sleep to give more time for an update to
  ## be received or subcribe to more active (or a larger number) of contracts
  ## to see updates print
  time.sleep(5)
  books.stop()
  ```
# Maintaining the Orderbook
FTX provides documentation on how to maintain the state of an orderbook, but does not provide concrete examples or a reference implementation.  This is unfortunate as although the documentation is fairly detailed, it still leaves plenty of questions.  For those that are curious, below we will walk through how to apply the steps as outlined in the [Book Depth](https://docs.ledgerx.com/reference/book-depth) section of the documentation.  Note that this is all handled for you by `OrderBookFeed`, so if you don't care about the details feel free to ignore this section.

### Queuing Action Report Messages
After establishing an authenticated connection to the websocket, the documentation linked above indicates we should begin queuing `action_report` messages for the contract(s) we are interested in.  The purpose of this is to ensure that we are listening to the websocket and receiving book updates _before_ we request the current state of the book.  If we first request the book state, and _then_ start receiving messages with updates to that book state, we may end up with a book as of Time 0 and the first message we receive which updates that book is from Time 2 - e.g. we missed a message. The notion of "time" here is formalized by the field `monotonic_clock` in the API docuemntation.  We only apply updates where the monotonic_clock is 1 greater than the existing monotonic_clock.

We can identify what contract (e.g. orderbook) an [action_report](https://docs.ledgerx.com/reference/market-data-feed) message effects by it's `contract_id` field.  Within this message are several other fields which will be used to update the book in different ways depending on the `status_type` field.  For now, we simply need to begin queuing messages, grouped by `contract_id` so that we can then request the current book state knowing that if there are clock gaps, we can use the queued data to bring the book current.  Before diving into the details of how to apply these messages to update a book, we will take a brief detour into loading the current state of the contract. 

### Loading the Initial Book State
Now that we are queuing messages we can [fetch the current state](https://docs.ledgerx.com/reference/book-state-contract) of the book for a given contract.  An example response will look like this:
```json
{
  "data": {
    "contract_id": 22210644,
    "book_states": [
      {
        "contract_id": 22210644,
        "price": 54067300,
        "size": 5,
        "is_ask": true,
        "clock": 313045,
        "mid": "c3dd293e56bb4acfbc6a27b671caeddb"
      },
      {
        "contract_id": 22210644,
        "price": 46600000,
        "size": 5,
        "is_ask": true,
        "clock": 313045,
        "mid": "3b6d505e02b14deab1e3828589cf4e7f"
      }
    ],
    "clock": 313045
  }
}
 ```
  
Only the first two book_state entries are shown above for concision.  Note that the "top-level" `contract_id` and `clock` are entirely redundant with those contained in each `book_state` object and can be safely ignored.  

In order to intialize our book, we want to create an object keyed by `contract_id` (so we can apply `action_reports` later) which records this information.  Here is an example implementation taken from the `OrderBook` class:

```python
class OrderBook():
    def __init__(self,contract_id,clock,messages):
        self.contract_id = contract_id
        self.clock = clock
        self.msgs  = dict()
        self.bids = SortedDict()
        self.asks = SortedDict()

        self.init_book(messages)

    def init_book(self,messages):
        for msg in messages:
            mid,px,sz= msg['mid'],msg['price'],msg['size']
            side = 'ask' if msg['is_ask'] else 'bid'
            self.msgs[mid] = msg 
            if side == 'ask':
                if px in self.asks:
                    self.asks[px] += sz 
                else:
                    self.asks[px] = sz 
            else:
                if -px in self.bids: # negative so largest bid is first
                    self.bids[-px] += sz 
                else:
                    self.bids[-px] = sz 
```
Let's assume the json response above is saved in a variable called `book_state`, then we could initalize this OrderBook as follows:
```python
all_my_orderbooks = {}
book_updates = book_state['data']['book_states']
ob = OrderBook(22210644,313045,book_updates)
all_my_orderbooks[cid] = ob # so we can apply action_reports later
```
For each message in `book_updates`, we extract the `price`, `size`, and `is_ask` fields and build the book depth by aggregating the size at each price-level for the relevant side of the book. In addition to building the bid and ask depth, we store each message in it's entirety keyed by `mid`.  This will become important for applying `action_reports` received from the websocket.

### Applying Action Reports
Now we have a book that has been initalized and can start updating with received messages from the websocket. There are [4 primary message](https://docs.ledgerx.com/reference/book-depth) types to handle.  Below we repeat much of the same information with somewhat different nomenclature to align with the process we've been following so far:



| status_type | Description                                     | How to Apply
| ------------| -----------------                               |-------------
| 200         |  order inserted                                 | Increase book `price` by `inserted_price` and `size` by `inserted_size`</br>Save the message and key it by `mid`
| 201         |  order filled                                   | Reduce `price` and `size` by `filled_price` and `filled_size`</br>Do this both for the book itself (e.g. adj bids/asks) as well as for the existing message keyed by `mid` in the book.</br> If `size` is zero delete both the `mid` and `price` level from book.
| 203         |  order canceled                                  | Retrieve `mid` from the orderbook, store it's price/size/side, and delete the `mid` from book</b> Then remove that price and size from `side` of book.
| 204         |  order canceled & replaced (only size changed, not price)        | Set `size` = `inserted_size` both for the book itself and for the existing message keyed by `mid` in the book



The above is still probably a bit fuzzy without seeing an implementation, but I hope combined with FTX's docuemntation it provides some incremental benefit.  Note that when we say "apply both to book itself and to the existing message keyed by the `mid` in the book", what we mean is this:

Assuming we receive an action_report with status_type == 201, e.g. a fill.  Fills will have the following fields (plus many others not relevant for this example):
```json
{
 "filled_price": 1000,
 "filled_size": 100,
 "mid": 2828,
 "lots_of": "other_fields"
}
```
There are two places we need to apply this message to update the orderbook:
 - orderbook[mid]
 - either orderbook[asks] or orderbook[bids] (depending on if is_ask is true or false)

The reason this is necessary is that if we later receive a 203 cancel message, we need to know the resting amount to remove from the book because cancel messages only show the original size of the order, not the current size.  We can only know the current size by adjusting the mid over time with fills and 204 cancel & replace orders which modify the size.

TODO: monotonic clock - ignore stale messages, restore from queue if clock gap.



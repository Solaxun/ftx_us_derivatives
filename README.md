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
Let's assume the [json response above]#(loading-the-initial-book-state) is saved in a variable called `book_state`, then we could initalize this OrderBook as follows:
```python
all_my_orderbooks = {}
book_updates = book_state['data']['book_states']
ob = OrderBook(22210644,313045,book_updates)
all_my_orderbooks[cid] = ob # so we can apply action_reports later
```
For each message in `book_updates`, we extract the `price`, `size`, and `is_ask` fields and build the book depth by aggregating the size at each price-level for the relevant side of the book. In addition to building the bid and ask depth, we store each message in it's entirety keyed by `mid`.  This will become important for applying `action_reports` received from the websocket.

### Applying Action Reports
Now we have a book that has been initalized and can start updating with received messages from the websocket. There are [4 primary message](https://docs.ledgerx.com/reference/book-depth) types to handle.  Below we repeat much of the same information from the linked documentation, but with more specific examples aligned with the terminology and variable names we've been working with so far.

**IMPORTANT**: For every message received, only update the book where the messages's `monotonic_clock` is exactly one greater than the book's current `monotonic_clock`. Messages with a monotonic_clock less than or equal to the book's current monotonic_clock can be ignored because their data is already incorporated into the book.  Messages with a monotonic_clock greater than one plus the book's current monotonic_clock indicate that we missed a message, and our book is now stale.  This can be remediated by restoring from the queued messages as mentioned in [Queuing Action Report Messages](#queuing-action-report-messages) or by requesting the book state as mentioned in [Loading the Initial Book State](#loading-the-initial-book-state).



| status_type | Description                                     | How to Apply
| ------------| -----------------                               |-------------
| 200         |  order inserted                                 |- Extract `inserted_size`, `inserted_price` and `is_ask` from the message</br>-  Adjust ob.bids or ob.asks for the order<sup>1</sup>:</br>`ob.[<side>][inserted_price] += inserted_size`</br>- Save the message in the book `ob.msgs[mid]=message`
| 201         |  order filled                                   | - Extract `filled_price`, `filled_size` and `mid` from the message</br>- Use the `mid` to extract and store the resting `price`, `size`, and `side` from ob.msgs[mid]</br>- Adjust ob.bids or ob.asks for the order<sup>1</sup>:</br>`ob.[<side>][price] -= filled_size`
| 203         |  order canceled                                  | - Retrieve `mid` from the message</br>- Use the `mid` to extract and store the resting `price`, `size`, and `side` from ob.msgs[mid]</br>- Delete the `mid` from book: `del ob.msgs[mid]`</br>- Adjust ob.bids or ob.asks by removing the canceled amount<sup>1</sup>:</br> `ob.[<side>][price] -= size`
| 204         |  order canceled & replaced (only size changed, not price)        | - Extract `mid` and `inserted_size` from the message</br>- Save `ob.msgs[mid][size]` in a variable called `resting_size`</br>- Set `ob.msgs[mid][size] = inserted_size`</br>- Extract `price` and `is_ask` from the msg</br>- Adjust ob.bids or ob.asks by adding the change in size<sup>1</sup>:</br> `ob.[<side>][price] += inserted_size - resting_size`

<sup>1</sup> _In the examples above \<side\> means asks if `is_ask` == true else bids_

### Concrete Examples:
Book Updating Code (shared by all messages below)
```python
def update_depth(self,func,is_ask,price,size):
    if is_ask:
        side = self.asks
    else:
        side = self.bids
        price = -price

    if price in side:
        cur_size = side[price]
        new_size = side[price] = func(cur_size,size)
        if new_size == 0:
            del side[price]
    else:
        side[price] = size
```
Order Inserted (200)
```python
## select fields from 200 action_report message
{
 "inserted_price": 1000,
 "inserted_size": 100,
 "mid": 2828,
 "lots_of": "other_fields"
}

## code to handle message
def add_order(self,msg):
    mid,price,size = msg['mid'], msg['inserted_price'], msg['inserted_size']
    if mid in self.msgs:
        self.msgs[mid]['size'] += size
    else:
        self.msgs[mid] = msg

    self.update_depth(lambda x,y: x + y,msg['is_ask'],price,size)

```
Order Filled (201)
```python
## select fields from 201 action_report message
{
 "filled_price": 1000,
 "filled_size": 100,
 "mid": 2828,
 "lots_of": "other_fields"
}

## code to handle message
def fill_order(self,msg):
    mid,price,size = msg['mid'], msg['filled_price'], msg['filled_size']
    # MID's we haven't seen are from the other side of the trade, e.g.
    # marketable limit or market orders that immediately fill by matching
    # our resting MID.  If any amount of the other side is unfilled, it will
    # end up as it's own message (201) and we will pick it up there.
    if mid in self.msgs:
        resting = self.msgs[mid]
        resting['price'] -= price
        resting['size']  -= size

        if resting['size'] == 0:
            del self.msgs[mid]
        if resting['size'] < 0:
            raise ValueError(
                '{}: filled={} > resting={}'.format(msg['cid'],size,resting['size'])
                )

        self.update_depth(lambda x,y: x - y,msg['is_ask'],price,size)   
```
Order Canceled (203)
```python
## select fields from 203 action_report message
{
 "original_price": 1000,
 "original_size": 100,
 "mid": 2828,
 "lots_of": "other_fields"
}

## code to handle message
def cancel_order(self,msg):
    mid = msg['mid']
    resting = self.msgs[mid]
    del self.msgs[mid]

    # remove the amount that was left in the order from bid or asks
    resting_price, resting_size = resting['price'], resting['size']
    self.update_depth(lambda x,y: x - y,resting['is_ask'],resting_price,
                      resting_size) 
```
Order Canceled & Replaced (204)
```python
## select fields from 204 action_report message
{
 "inserted_price": 1000,
 "inserted_size": 100,
 "mid": 2828,
 "lots_of": "other_fields"
}

## code to handle message
def cancel_and_replace(self,msg):
    mid, inserted_size = msg['mid'], msg['inserted_size']
    resting = self.msgs[mid]
    resting_price = resting['price']
    resting_size = resting['size']

    resting['size'] = inserted_size

    if msg['is_ask']:
        self.asks[resting_price] += inserted_size - resting_size
    else:
        self.bids[-resting_price] += inserted_size - resting_size
```




from ftx.client import Client
from ftx.websocket import Websocket
from ftx.orderbook_feed import OrderBookFeed
import time

if __name__ == "__main__":

    ###########################
    ## REST Client
    ###########################
    API_KEY = None
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

    ## listen for 3 seconds and then stop
    time.sleep(3)
    ws.stop()
    time.sleep(2)
    print('Done receiving Websocket messages...')
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
        contracts=[22229264, 22209160,22229265,22229263,22229262,22213562],
        on_book=do_something_with_book        
    )

    print('Displaying orderbook updates...')
    time.sleep(2)

    books.start()

    ## Listen for a while then stop. 

    ## Note: if none of the books subscribed to update during this time you won't
    ## see anything print.  Increase the sleep to give more time for an update to
    ## be received or subcribe to more active (or a larger number) of contracts
    ## to see updates print
    time.sleep(10)
    books.stop()
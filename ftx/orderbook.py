from sortedcontainers import SortedDict

class OrderBook():
    def __init__(self,contract_id,clock,messages,contract_info):
        self.contract_id = contract_id
        self.clock = clock
        self.contract_info = contract_info
        self.msgs  = dict()
        self.bids = SortedDict()
        self.asks = SortedDict()

        self.init_book(messages)

    def init_book(self,messages):
        for msg in messages:
            mid,px,sz= msg['mid'],msg['price'],msg['size']
            side = 'ask' if msg['is_ask'] else 'bid'
            self.msgs[mid] = msg # maybe trim down to price/sz/side only?
            if side == 'ask':
                if px in self.asks:
                    self.asks[px] += sz 
                else:
                    self.asks[px] = sz 
            else:
                if -px in self.bids:
                    self.bids[-px] += sz 
                else:
                    self.bids[-px] = sz 

    @property
    def bid(self):
        if not self.bids:
            return (0,0)
        price,size = self.bids.peekitem(0)
        return -price, size

    @property
    def ask(self):
        if not self.asks:
            return (0,0)
        price,size = self.asks.peekitem(0)
        return price,size

    def update_clock(self,newclock):
        self.clock = newclock

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
            if new_size < 0:
                raise ValueError(
                    'order size of {} exceeds resting size of {}'.format(size,cur_size)
                    )
        else:
            side[price] = size

    def add_order(self,msg):
        mid,price,size = msg['mid'], msg['inserted_price'], msg['inserted_size']
        if mid in self.msgs:
            self.msgs[mid]['size'] += size
        else:
            self.msgs[mid] = msg

        self.update_depth(lambda x,y: x + y,msg['is_ask'],price,size)

    def fill_order(self,msg):
        mid,price,size = msg['mid'], msg['filled_price'], msg['filled_size']
        # MID's we haven't seen are from the other side of the trade, e.g.
        # marketable limit or market orders that immediately fill by matching
        # our resting MID.  If any amount of the other side is unfilled, it will
        # end up as it's own message (201) and we will pick it up there.
        if mid in self.msgs:
            resting = self.msgs[mid]
            resting_size = resting['size'] = resting['size'] - size
            if resting_size == 0:
                del self.msgs[mid]
            if resting_size < 0:
                raise ValueError(
                    '{}: filled={} > resting={}'.format(msg['cid'],size,resting_size)
                    )
           
            self.update_depth(lambda x,y: x - y,msg['is_ask'],price,size)   

    def cancel_order(self,msg):
        mid = msg['mid']
        resting = self.msgs[mid]
        del self.msgs[mid]

        # remove the amount that was left in the order from bid or asks
        resting_price, resting_size = resting['price'], resting['size']
        self.update_depth(lambda x,y: x - y,resting['is_ask'],resting_price,
                          resting_size)
    
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

    def __str__(self):
        bidpx,bidsz = self.bid
        askpx,asksz = self.ask

        return '{}(cid={},name={},bid=({:,}, {:,}),ask=({:,}, {:,}))'.format(
            self.__class__.__name__,
            self.contract_id,
            self.contract_info['label'],
            bidpx,
            bidsz,
            askpx,
            asksz
            )

    def __len__(self):
        return len(self.bids) + len(self.asks)
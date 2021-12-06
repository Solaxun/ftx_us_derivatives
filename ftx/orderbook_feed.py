import json
import requests
import threading
import time
from collections import defaultdict, deque
from copy import deepcopy

from ftx.orderbook import OrderBook
from ftx.websocket import Websocket


class OrderBookFeed(Websocket):
    def __init__(self,api_key=None,contracts=None,on_book=lambda b: b,debug=False):
        if api_key is None:
            raise ValueError(
                'Authentication is required for OrderBookFeed. ' + \
                'Please provide an `api_key`'
                )
        super().__init__(api_key=api_key)
        self.last_heartbeat = None
        self.book_states_url = 'https://trade.ledgerx.com/api/book-states/'
        self.contracts_url = 'https://api.ledgerx.com/trading/contracts'
        self.action_reports = defaultdict(lambda: deque(maxlen=100))
        self.contracts = contracts
        self.all_active_contracts = {}
        self.books = {}
        self.lock = threading.Lock()
        self.on_book = on_book
        self.debug = debug

    def start(self):
        # start handling websocket messages
        super().start()
        # load all actively traded contracts
        t1 = threading.Thread(target=self.load_contracts,args=())
        t1.start()
        # briefly sleep to ensure thread running websocket is able to receive
        # some messages before we initialize the orderbook.  This helps lessen
        # the chance of monotonic clock gaps as otherwise the threads could race
        # and we could end up loading a book before listening to the socket, and 
        # then by the time we listen for messages we've missed a few.
        time.sleep(2)
        # load book state for contracts we are interested in
        self.subscribe(self.contracts)
        t1.join()

    def load_contracts(self):
        url = 'https://api.ledgerx.com/trading/contracts?active=true'
        r = requests.get(url)
        if r.status_code != 200:
            raise ValueError('status: '.format(r.status_code))
        contracts = r.json()['data']
        for c in contracts:
            cid = c['id']
            self.all_active_contracts[cid] = c

    def subscribe(self,contracts):
        if contracts[0] == 'all':
            contracts = self.all_active_contracts.keys()        
        threads = []
        for c in contracts:
            t = threading.Thread(target=self.init_book_from_cid,args=(c,))
            threads.append(t)
            t.start()
            # print('start')
        for t in threads:
            t.join()
            # print('done')

    def on_open(self,ws):
        print('Connection to {} succeded!'.format(self.url))

    def on_message(self,ws,msg):
        msg = json.loads(msg)
        mtype = msg['type']

        if mtype == 'action_report':
            self.handle_action_report(msg)
        elif mtype == 'book_top': # already handled in action_reports
            pass
        elif mtype == 'heartbeat':
            self.update_heartbeat(msg)
        else:
            print('other_msg: ',mtype)

    def handle_action_report(self,msg):
        cid = msg['contract_id']
        # either we haven't subscribed to the contract, or the book has not yet been
        # initialized with a snapshot - ignore msg in either case
        if not cid in self.contracts or cid not in self.books:
            return
        # first save action_report msg so we can load from history when there are clock gaps
        self.action_reports[cid].append(msg)
        #TODO: haven't yet init book
        # book exists, try to apply actions - if gap exists try to apply from queued actions
        book_to_update = self.books[cid]

        action_report_clock = msg['clock']

        if action_report_clock > book_to_update.clock + 1:
            print('{} book clock {} < action_report_clock - 1, loading hist{}'.format(
                cid,book_to_update.clock,action_report_clock))
            self.apply_historical_action_reports(book_to_update,cid,action_report_clock)
        
        elif action_report_clock <= book_to_update.clock:
            print('{} book clock {} > STALE action_report_clock {}'.format(
                cid,book_to_update.clock,action_report_clock))
            return
        else:
            self.apply_action_report(book_to_update,msg)

        # defensively copy since we are handing this off but the websocket thread
        # will still be modifying the underlying book on new messages
        book_copy = deepcopy(book_to_update)
        self.on_book(book_copy)

    def apply_action_report(self,book,msg):
        action_type = msg['status_type']

        if action_type == 200:
            book.add_order(msg)
        elif action_type == 201:
            # os.system('say "trade filled"')
            book.fill_order(msg)
        elif action_type == 202:
            print('MARKET ORDER NOT FILLED: ', msg)
        elif action_type == 203:
            book.cancel_order(msg)
        elif action_type == 204:          
            book.cancel_and_replace(msg)

        book.update_clock(msg['clock'])

    def on_close(self,ws,status_cd,msg):
        print('Closed connection to: {}'.format(self.url))
        if msg:
            print(msg)
        if status_cd:
            print('status_cd = {}'.format(status_cd))

    def on_error(self,ws,error):
        print('ERROR: ',error)
        # ws.close()
        # print('closed')
        ws.close()
        # ws.on_close(ws,None,'Connection to {} closed.'.format(self.url))

    def apply_historical_action_reports(self,book,cid,toclock):
        """ remove until we find action_report with clock = book.clock + 1"""

        print("*LOADING FROM QUEUE*")
        # sort the queue in case msgs arrive out of clock order
        # sort in reverse so we can efficiently pop from right (oldest)
        recent_action_reports = sorted(self.action_reports[cid],reverse=True)
        print('checking {} queued reports'.format(len(recent_action_reports)))
        while recent_action_reports:
            action_report = recent_action_reports.pop()
            print('queue clock: {}'.format(action_report['clock']))
            if action_report['clock'] == book.clock + 1:            
                self.apply_action_report(book,action_report)

        if book.clock != toclock:
            # t = threading.Thread(target=self.init_book_from_cid,args=(cid,))

            # TODO: try getting a newer book snapshot up to maxtries times
            # while this is happenig we are still queuing action_reports
            # so hopefully chances of this happening several times in a row
            # is low
            raise ValueError('could not bring contract {} current'.format(cid))
        else:
            print('*succesfully restored book from history*')

    #TODO: subscribe to a certain depth.. only call on_book if depth is <= that depth
    def init_book_from_cid(self,cid):
        uri = self.book_states_url + str(cid)
        headers={
            'Accept':'application/json',
            'Authorization':'JWT {}'.format(self.api_key)
            }
        
        r = requests.get(uri,headers=headers)
        if r.status_code != 200:
            raise ValueError('resp code: {}'.format(r.status_code))
            
        book_state = json.loads(r.text)['data']
        toplevel_clock = book_state['clock']
        entries = book_state['book_states']

        contract_info = self.all_active_contracts[cid]
        book = OrderBook(cid,toplevel_clock,entries,contract_info)
        with self.lock:
            self.books[cid] = book

    def update_heartbeat(self,msg):
        self.last_heartbeat = msg['timestamp']
        self.run_id = msg['run_id']
        #TODO: logic to handle hard restarts based on runid, reconn after 
        #certain time elapsed, etc.
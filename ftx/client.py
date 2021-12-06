import requests
from copy import deepcopy
from urllib.parse import urlencode

class Client():
    base_url = 'https://api.ledgerx.com/trading'
    contracts_url = base_url + '/contracts'
    positions_url = base_url + '/positions'
    trades_url = base_url + '/trades'
    transactions_url = 'https://api.ledgerx.com/funds/transactions'

    def __init__(self,api_key=None):
        self.api_key = api_key

    def check_response_code(getfunc):
        def handle_errors(self,url):
            r = getfunc(self,url)
            code = r.status_code

            if code == 400:
                raise Exception('Bad request {}'.format(r.text))
            elif code == 401:
                raise Exception('Bad credentials? {}'.format(r.text))
            elif code == 403:
                raise Exception('Authentication required {}'.format(r.text))
            elif code == 404:
                raise Exception('bad URL {}'.format(url))
            elif code == 200:
                return r.json()
        return handle_errors
    
    @check_response_code
    def auth_get(self,url):
        if self.api_key is None:
            raise Exception('Authentication is required for this endpoint.')
        r = requests.get(
            url,
            headers = {
                'Accept':'application/json',
                'Authorization':'JWT {}'.format(self.api_key)
            })
        return r
    
    @check_response_code
    def get(self,url):
        r = requests.get(url)
        return r

    def list_contracts(self,**params):
        """Returns a list of contracts.
        
        This endpoint has a rate limit of 10 requests per minute, 
        and 50 requests per 10 minutes."""

        url = self.contracts_url + '?' + urlencode(params)
        return self.get(url)
        
    def list_traded_contracts(self,**params):
        """Returns a list of contracts that you have traded."""
        url = self.contracts_url + '/traded?' + urlencode(params)
        return self.auth_get(url)

    def retrieve_contract(self,id):
        """Returns contract details for a single contract ID."""
        url = self.contracts_url + '/{}'.format(id)
        return self.get(url)

    def retrieve_position_for_contract(self,id):
        """Returns your position for a given contract."""
        url = self.contracts_url + '/{}/position'.format(id)
        return self.auth_get(url)

    def get_contract_ticker(self,id,**params):
        """Snapshot information about the current best bid/ask, 24h volume, 
        and last trade
        
        This endpoint has a rate limit of 10 requests per minute.
        For real-time updates, it is recommended to connect to the Websocket 
        Market Data Feed."""
        #TODO: will 404 for expired ID's
        url = self.contracts_url + '/{}/ticker'.format(id) + urlencode(params)
        return self.auth_get(url)

    def list_positions(self,**params):
        url = self.positions_url  + '?' + urlencode(params)
        return self.auth_get(url)

    def list_trades_for_position(self,id):
        #TODO: this 404's rather than returning empty results
        #404 could mean the id specified is invalid.. pass
        #the 404 through
        url = self.positions_url + '/{}/trades'.format(id)
        return self.auth_get(url)

    def list_your_trades(self,**params):
        url = self.trades_url  + '?' + urlencode(params)
        return self.auth_get(url)

    def list_all_trades(self,**params):
        url = self.trades_url  + '/global?' + urlencode(params)
        return self.get(url)

    def list_transactions(self,**params):
        url = self.transactions_url  + '?' + urlencode(params)
        return self.auth_get(url)
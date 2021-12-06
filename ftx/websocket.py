import websocket
import threading

class Websocket():
    def __init__(self,url='wss://api.ledgerx.com/ws',api_key=None):
        self.api_key = api_key
        self.url = url
        self.ws_url = url + '?token=' + self.api_key

    def start(self):
        self.ws = websocket.WebSocketApp(
            url = self.ws_url,
            on_open = self.on_open,
            on_message = self.on_message,
            on_close = self.on_close,
            on_error = self.on_error
            )

        self.t = threading.Thread(target=self.ws.run_forever)
        self.t.daemon = True
        self.t.start()

    def on_open(self,ws):
        raise NotImplementedError

    def on_message(self,ws,msg):
        raise NotImplementedError

    def on_close(self,ws,close_status_cd,msg):
        raise NotImplementedError

    def on_error(self,ws,error):
        raise NotImplementedError

    def stop(self):
        self.ws.close()
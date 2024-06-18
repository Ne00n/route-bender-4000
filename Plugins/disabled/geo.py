import requests

class geo():
    
    def __init__(self):
        print("Loading ping.py")

    def prepare(self):
        return True

    def unreachable(self,ip):
        return False

    def geo(self,ip):
        try:
            req = requests.get(f"https://geo.serv.app/{ip}", timeout=(3, 3))
            if req.status_code == 200:
                data = req.json()
                highest = data['highest']
                if data['score'] and data['score'][highest] > 90: return data['ips']
            return False
        except Exception as err:
            return False
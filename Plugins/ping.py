import requests

class ping():
    
    def __init__(self):
        print("Loading ping.py")

    def prepare(self):
        return True

    def unreachable(self,ip):
        try:
            req = requests.get(f"https://ping.serv.app/{ip}", timeout=(3, 3))
            if req.status_code == 200:
                data = req.json()
                if data['next'] == False: return data['ips']
            return False
        except Exception as err:
            return False
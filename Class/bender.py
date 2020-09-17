import subprocess, time, json, re

nodes,network = [],[]

class Bender:
    def __init__(self):
        global nodes,network
        print("Loading config")
        with open('nodes.json') as handle:
            nodes = json.loads(handle.read())
        print("Loading pmacct")
        with open('/tmp/pmacct_avg.json', 'r') as f:
            network = f.read()

    def cmd(self,command,interactive=False):
        if interactive == True:
            return subprocess.check_output(command).decode("utf-8")
        else:
            subprocess.call(command, shell=True)

    def clear(self):
        print("Flushing Routing Table...")
        subprocess.run(['ip', 'route', 'flush','table','BENDER'])

    def prepare(self):
        global nodes
        print("Prepare")
        base = 400
        tables = re.findall("^([0-9]+)",self.cmd(['cat', '/etc/iproute2/rt_tables'],True), re.MULTILINE | re.DOTALL)
        inetList = re.findall("(10[0-9.]+?252\.[0-9]+)",self.cmd(['ip','addr','show','lo'],True), re.MULTILINE)
        route = subprocess.Popen(["ip", "rule", "list","table","BENDER","all"], stdout=subprocess.PIPE,stderr=subprocess.PIPE).stdout.read().decode('utf-8')
        for server in nodes:
            lastByte = re.findall("^([0-9.]+)\.([0-9]+)",server, re.MULTILINE | re.DOTALL)
            node = str(base + int(lastByte[0][1]))
            if not "BENDER" in route:
                self.cmd('ip rule add from 0.0.0.0/0 table BENDER')
            if node not in tables:
                self.cmd(["echo '"+node+" Node"+node+"' >> /etc/iproute2/rt_tables"])
            if "10.0.252."+lastByte[0][1] not in inetList:
                self.cmd("ip addr add 10.0.252."+lastByte[0][1]+"/32 dev lo")
            self.cmd('ip route flush table Node'+node)
            self.cmd('ip rule add from 10.0.252.'+lastByte[0][1]+'/32 table Node'+node)
            self.cmd('ip route add default via 10.0.251.'+lastByte[0][1]+' table Node'+node)

    def getAvrg(self,fping):
        parsed = re.findall("([0-9.]+).*?([0-9]+.[0-9]).*?([0-9])% loss",fping, re.MULTILINE)
        latency = []
        for ip,ms,loss in parsed:
            latency.append(ms)
        latency.sort()
        return round((float(latency[0]) + float(latency[1]) + float(latency[2])) / 3,2)

    def run(self):
        global nodes,network
        self.prepare()
        print("Launching")
        for row in network.split('\n'):
            if row.strip() == "": continue
            line = json.loads(row)

            if '239.255.255.' in line['ip_dst']: continue
            if '224.0.0.' in line['ip_dst']: continue
            if '192.168.' in line['ip_dst']: continue
            if '172.16.' in line['ip_dst']: continue
            if '10.0.' in line['ip_dst']: continue

            route = subprocess.Popen(["ip", "r", "get", line['ip_dst']], stdout=subprocess.PIPE,stderr=subprocess.PIPE).stdout.read().decode('utf-8')
            if 'vxlan1' in route:
                print("Route for",line['ip_dst'],"already exists")
                continue

            latency = []
            direct = subprocess.Popen(["fping", "-c5", line['ip_dst']], stdout=subprocess.PIPE,stderr=subprocess.PIPE).stderr.read().decode('utf-8')
            for server in nodes:
                if '100%' in direct:
                    print("Target",line['ip_dist'],"not reachable, skipping")
                    continue
                lastByte = re.findall("^([0-9.]+)\.([0-9]+)",server, re.MULTILINE | re.DOTALL)
                result = subprocess.run(["fping", "-c5", line['ip_dst'], "-S",server], stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                parsed = re.findall("([0-9.]+).*?([0-9]+.[0-9]).*?([0-9])% loss",result.stdout.decode('utf-8'), re.MULTILINE)
                if parsed:
                    avrg = self.getAvrg(result.stdout.decode('utf-8'))
                    latency.append([avrg,lastByte[0][1]])
                    print("Got",str(avrg)+"ms","to",line['ip_dst'],"from",server)
                else:
                    print(result)
            latency.sort()
            direct = self.getAvrg(direct)
            diff = direct - float(latency[0][0])
            if diff < 1 and diff > 0:
                print("Difference less than 1ms, skipping",float(direct),"vs",float(latency[0][0]),"for",line['ip_dst'])
            elif diff < 1:
                print("Direct route is better, keeping it for",line['ip_dst'],"Lowest we got",float(latency[0][0]),"ms vs",int(direct),"ms direct")
            elif float(latency[0][0]) < int(direct):
                print("Routed",line['ip_dst'],"via","10.0.251."+latency[0][1],"improved latency by",diff,"ms")
                subprocess.run(['ip','route','add',line['ip_dst']+"/32",'via',"10.0.251."+latency[0][1],'dev',"vxlan1",'table','BENDER'])

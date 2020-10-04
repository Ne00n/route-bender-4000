import subprocess, time, json, re
from multiprocessing import Process

nodes,network = [],[]

class Bender:
    def __init__(self,path):
        global nodes,network
        print("Loading config")
        with open(path+'/nodes.json') as handle:
            nodes = json.loads(handle.read())
        print("Loading pmacct")
        with open('/tmp/pmacct_avg.json', 'r') as f:
            network = f.read()

    def cmd(self,cmd):
        p = subprocess.run(cmd, stdin=None, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
        return [p.stdout.decode('utf-8'),p.stderr.decode('utf-8')]

    def clear(self):
        print("Flushing Routing Table...")
        self.cmd('ip route flush table BENDER')

    def prepare(self):
        global nodes
        print("Prepare")
        base = 400
        tables = re.findall("^([0-9]+)",self.cmd('cat /etc/iproute2/rt_tables')[0], re.MULTILINE | re.DOTALL)
        inetList = re.findall("(10[0-9.]+?252\.[0-9]+)",self.cmd('ip addr show lo')[0], re.MULTILINE)
        route = self.cmd("ip rule list table BENDER all")[0]
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
        latency = []
        parsed = re.findall("([0-9.]+).*?([0-9]+.[0-9]).*?([0-9])% loss",fping, re.MULTILINE)
        for ip,ms,loss in parsed:
            latency.append(ms)
        latency.sort()
        return round((float(latency[0]) + float(latency[1]) + float(latency[2])) / 3,2)

    def magic(self,line):
        route = self.cmd("ip r get "+line['ip_dst'])[0]
        if 'vxlan1' in route:
            print(line['ip_dst'],"route already exists")
            exit()

        origin = 0
        direct = self.cmd("fping -c5 "+line['ip_dst'])
        if '100%' in direct[1]:
            print(line['ip_dst'],"not reachable, trying to MTR")
            result = self.cmd('mtr '+line['ip_dst']+' --report --report-cycles 4 --no-dns')
            parsed = re.findall("-- ([0-9.]+)",result[0], re.MULTILINE)
            lastIP = parsed[len(parsed) -1]
            if lastIP != "???":
                direct = self.cmd("fping -c5 "+lastIP)
            if '100%' in direct[1]:
                print(line['ip_dst'],"("+lastIP+") not reachable, skipping")
                exit()
            else:
                origin = line['ip_dst']
                line['ip_dst'] = lastIP

        latency = []
        for server in nodes:
            lastByte = re.findall("^([0-9.]+)\.([0-9]+)",server, re.MULTILINE | re.DOTALL)
            result = self.cmd("fping -c5 "+line['ip_dst']+" -S "+server)[0]
            parsed = re.findall("([0-9.]+).*?([0-9]+.[0-9]).*?([0-9])% loss",result, re.MULTILINE)
            if parsed:
                avrg = self.getAvrg(result)
                latency.append([avrg,lastByte[0][1]])
                print("Got",str(avrg)+"ms","to",line['ip_dst'],"from",server)
            else:
                print(line['ip_dst']+" is not reachable via "+server)
        latency.sort()
        direct = self.getAvrg(direct[0])
        diff = direct - float(latency[0][0])
        if diff < 1 and diff > 0:
            print("Difference less than 1ms, skipping",float(direct),"vs",float(latency[0][0]),"for",line['ip_dst'])
        elif diff < 1:
            print("Direct route is better, keeping it for",line['ip_dst'],"Lowest we got",float(latency[0][0]),"ms vs",int(direct),"ms direct")
        elif float(latency[0][0]) < int(direct):
            print("Routed",line['ip_dst'],"via","10.0.251."+latency[0][1],"improved latency by",diff,"ms")
            if origin == 0:
                self.cmd('ip route add '+line['ip_dst']+"/32 via 10.0.251."+latency[0][1]+" dev vxlan1 table BENDER")
            else:
                self.cmd('ip route add '+origin+"/32 via 10.0.251."+latency[0][1]+" dev vxlan1 table BENDER")

    def run(self):
        global nodes,network
        ips = []
        self.prepare()
        print("Launching")
        for row in network.split('\n'):
            if row.strip() == "": continue
            line = json.loads(row)
            #Filter Local/Multicast traffic
            if '239.255.255.' in line['ip_dst']: continue
            if '224.0.0.' in line['ip_dst']: continue
            if '192.168.' in line['ip_dst']: continue
            if '172.16.' in line['ip_dst']: continue
            if '10.0.' in line['ip_dst']: continue
            #Filter double entries
            if line['ip_dst'] in ips: continue
            ips.append(line['ip_dst'])
            #Filter less than 500 bytes
            if line['bytes'] < 500: continue
            #Lets go bending
            p = Process(target=self.magic, args=([line]))
            p.start()
            print("Launched",line['ip_dst'])
        for server in nodes:
            lastByte = re.findall("^([0-9.]+)\.([0-9]+)",server, re.MULTILINE | re.DOTALL)
            direct = self.cmd('fping -c3 10.0.251.'+lastByte[0][1])[1]
            if '100%' in direct:
                routes = self.cmd('ip route show table BENDER via 10.0.251.'+lastByte[0][1])[0]
                parsed = re.findall("^([0-9.]+)",routes, re.MULTILINE | re.DOTALL)
                for entry in parsed:
                    self.cmd('ip route del '+entry+'/32 via 10.0.251.'+lastByte[0][1]+' dev vxlan1 table BENDER')

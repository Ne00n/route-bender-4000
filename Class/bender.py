import subprocess, random, pyasn, time, json, re, os
from multiprocessing import Queue
from datetime import datetime
from threading import Thread

class Bender:
    def __init__(self,path):
        self.path = path
        print("Loading asn")
        self.asndb = pyasn.pyasn(path+'/asn.dat')
        print("Loading nodes")
        with open(path+'/config/nodes.json') as handle:
            self.nodes = json.loads(handle.read())
        print("Loading config")
        with open(path+'/config/config.json') as handle:
            self.config = json.loads(handle.read())
        print("Loading pmacct")
        with open('/tmp/pmacct_avg.json', 'r') as f:
            self.network = f.read()
        if os.path.exists(path+'/data/ignore.json'):
            print("Loading ignore.json")
            with open(path+'/data/ignore.json') as handle:
                self.ignore = json.loads(handle.read())
        else:
            self.ignore = {}
        if os.path.exists(path+'/data/loadBalancing.json'):
            print("Loading loadBalancing.json")
            with open(path+'/data/loadBalancing.json') as handle:
                self.loadBalancing = json.loads(handle.read())
        else:
            self.loadBalancing = {}

    def cmd(self,cmd):
        p = subprocess.run(cmd, stdin=None, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
        return [p.stdout.decode('utf-8'),p.stderr.decode('utf-8')]

    def clear(self):
        print("Flushing Routing Table...")
        self.cmd('ip route flush table BENDER')

    def prepare(self):
        print("Prepare")
        base = 400
        tables = re.findall("^([0-9]+)",self.cmd('cat /etc/iproute2/rt_tables')[0], re.MULTILINE | re.DOTALL)
        inetList = re.findall("(10[0-9.]+?252\.[0-9]+)",self.cmd('ip addr show lo')[0], re.MULTILINE)
        route = self.cmd("ip rule list table BENDER all")[0]
        if not "BENDER" in route:
            self.cmd('ip rule add from 0.0.0.0/0 table BENDER')
        for server in self.nodes:
            lastByte = re.findall("^([0-9.]+)\.([0-9]+)",server, re.MULTILINE | re.DOTALL)
            node = str(base + int(lastByte[0][1]))
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
        del parsed[0] #drop the first ping result
        for ip,ms,loss in parsed:
            latency.append(ms)
        latency.sort()
        if len(latency) < 5: return 5000
        return round((float(latency[0]) + float(latency[1]) + float(latency[2])) / 3,2)

    def isPrivate(self,ip):
        #Source https://stackoverflow.com/questions/691045/how-do-you-determine-if-an-ip-address-is-private-in-python
         priv_lo = re.compile("^127\.\d{1,3}\.\d{1,3}\.\d{1,3}$")
         priv_24 = re.compile("^10\.\d{1,3}\.\d{1,3}\.\d{1,3}$")
         priv_20 = re.compile("^192\.168\.\d{1,3}.\d{1,3}$")
         priv_16 = re.compile("^172.(1[6-9]|2[0-9]|3[0-1]).[0-9]{1,3}.[0-9]{1,3}$")
         return (priv_lo.match(ip) or priv_24.match(ip) or priv_20.match(ip) or priv_16.match(ip))

    def fpingSource(self,server,ip):
        lastByte = re.findall("^([0-9.]+)\.([0-9]+)",server, re.MULTILINE | re.DOTALL)
        if server == "direct":
            result = self.cmd("fping -c6 "+ip)[0]
        else:
            result = self.cmd("fping -c6 "+ip+" -S "+server)[0]
        parsed = re.findall("([0-9.]+).*?([0-9]+.[0-9]).*?([0-9])% loss",result, re.MULTILINE)
        return parsed,result,lastByte

    def fpingWorker(self,queue,outQueue):
        while queue.qsize() > 0 :
            data = queue.get()
            parsed,result,lastByte = self.fpingSource(data['server'],data['ip'])
            outQueue.put({"parsed":parsed,"result":result,"lastByte":lastByte,"ip":data['ip'],"server":data['server']})

    def magic(self,line,force):
        route = self.cmd("ip r get "+line['ip_dst'])[0]
        if 'vxlan1' in route:
            print(line['ip_dst'],"route already exists")
            exit()

        origin = 0
        direct = self.cmd("fping -c6 "+line['ip_dst'])
        if '100%' in direct[1]:
            print(line['ip_dst'],"not reachable, trying to MTR")
            result = self.cmd('mtr '+line['ip_dst']+' --report --report-cycles 4 --no-dns')
            parsed = re.findall("-- ([0-9.]+)",result[0], re.MULTILINE)
            lastIP = parsed[len(parsed) -1]
            if self.isPrivate(lastIP):
                print(lastIP+" is private, skipping")
                exit()
            if lastIP != "???":
                direct = self.cmd("fping -c6 "+lastIP)
            if '100%' in direct[1]:
                print(line['ip_dst'],"("+lastIP+") not reachable, skipping")
                exit()
            else:
                origin = line['ip_dst']
                line['ip_dst'] = lastIP

        latency,queue,outQueue,count = [],Queue(),Queue(),0
        for server in self.nodes:
            queue.put({"server":server,"ip":line['ip_dst']})
        threads = [Thread(target=self.fpingWorker, args=(queue,outQueue,)) for _ in range(int(len(self.nodes) / 3))]
        for thread in threads:
            thread.start()
        while len(self.nodes) != count:
            while not outQueue.empty():
                data = outQueue.get()
                if data['parsed']:
                    avrg = self.getAvrg(data['result'])
                    latency.append([avrg,data['lastByte'][0][1]])
                    print("Got",str(avrg)+"ms","to",data['ip'],"from",data['server'])
                else:
                    print(line['ip_dst']+" is not reachable via "+data['server'])
                count += 1
            time.sleep(0.05)
        for thread in threads:
            thread.join()
        if not latency: return
        latency.sort()
        direct = self.getAvrg(direct[0])
        diff = direct - float(latency[0][0])
        if diff < 2 and diff > 0 and force == False:
            print("Difference less than 2ms, skipping",float(direct),"vs",float(latency[0][0]),"for",line['ip_dst'])
        elif diff < 2 and force == False:
            print("Direct route is better, keeping it for",line['ip_dst'],"Lowest we got",float(latency[0][0]),"ms vs",int(direct),"ms direct")
        elif float(latency[0][0]) < int(direct) or force == True:
            if origin == 0: origin = line['ip_dst']
            suffix = "/32"
            asndata = self.asndb.lookup(origin)
            if asndata[0] is not None:
                group = self.checkASNGroup(asndata[0])
                if group != False and group['settings']['loadBalancing'] is False:
                    if group['asns'] in self.loadBalancing:
                        latency[0][1] = self.loadBalancing[group['asns']]
                    else:
                        self.loadBalancing[group['asns']] = latency[0][1]
                    suffix = group['settings']['route']
                if suffix == "/32":
                    for asn,settings in self.config['ASN'].items():
                        if int(asn) == int(asndata[0]):
                            suffix = settings['route']
                            if self.config['ASN'][asn]['loadBalancing'] is False:
                                if asn in self.loadBalancing:
                                    latency[0][1] = self.loadBalancing[asn]
                                else:
                                    self.loadBalancing[asn] = latency[0][1]
                            break
            if suffix == "/32":
                self.cmd('ip route add '+origin+"/32 via 10.0.251."+latency[0][1]+" dev vxlan1 table BENDER")
            else:
                if suffix == "dyn":
                    origin = asndata[1].split("/")[0]
                    suffix = "/"+asndata[1].split("/")[1]
                else:
                    origin = '.'.join(origin.split('.')[:-1]+["0"])
                self.cmd('ip route add '+origin+suffix+" via 10.0.251."+latency[0][1]+" dev vxlan1 table BENDER")
            print("Routed",line['ip_dst'],"via","10.0.251."+latency[0][1],"improved latency by",diff,"ms")

    def checkNode(self,server):
        lastByte = re.findall("^([0-9.]+)\.([0-9]+)",server, re.MULTILINE | re.DOTALL)
        print("Checking if","10.0.251."+lastByte[0][1],"is alive")
        direct = self.cmd('fping -c3 10.0.251.'+lastByte[0][1])[1]
        if '100%' in direct:
            routes = self.cmd('ip route show table BENDER via 10.0.251.'+lastByte[0][1])[0]
            parsed = re.findall("^([0-9.]+\/[0-9]+)",routes, re.MULTILINE | re.DOTALL)
            for entry in parsed:
                self.cmd('ip route del '+entry+' via 10.0.251.'+lastByte[0][1]+' dev vxlan1 table BENDER')

    def checkASNGroup(self,asn):
        for asnsRaw,settings in self.config['ASNGroups'].items():
            asns = asnsRaw.split(",")
            if str(asn) in asns:
                return {"asns":asnsRaw,"settings":settings}
                break
        return False

    def debug(self):
        ip = input("IP: ")
        print("Running fping")
        count,queue,outQueue = 0,Queue(),Queue()
        queue.put({"server":"direct","ip":ip})
        for server in self.nodes:
            queue.put({"server":server,"ip":ip})
        threads = [Thread(target=self.fpingWorker, args=(queue,outQueue,)) for _ in range(int(len(self.nodes) / 3))]
        for thread in threads:
            thread.start()
        results = {}
        while len(self.nodes)+1 != count:
            while not outQueue.empty():
                data = outQueue.get()
                if data['parsed']:
                    results[data['server']] = self.getAvrg(data['result'])
                else:
                    print(data['ip']+" is not reachable via "+data['server'])
                count += 1
            time.sleep(0.05)
        for thread in threads:
            thread.join()
        results = {k: results[k] for k in sorted(results, key=results.get)}
        print("--- Direct ---")
        directAvrg = results["direct"]
        print("Got " + str(directAvrg) +"ms direct")
        del results["direct"]
        print("--- Top 5 ---")
        save,count,bendable = 0,0,False
        for server, latency in results.items():
            if count < 5: print("Got " + str(latency)+"ms" + " from " + server)
            if latency < directAvrg +2:
                if save is 0: save = directAvrg - latency
                bendable = True
            count += 1
        print("--- Save ---")
        print("Theoretical save:",str(round(save,2))+"ms")
        print("Bendable:",bendable)
        print("--- end ---")

    def run(self):
        ips,asnList,threads = [],[],[]
        self.prepare()
        print("Launching")
        for row in self.network.split('\n'):
            if row.strip() == "": continue
            line = json.loads(row)
            #Filter Local/Multicast traffic
            if '239.255.255.' in line['ip_dst']: continue
            if '224.0.0.' in line['ip_dst']: continue
            if '192.168.' in line['ip_dst']: continue
            if '172.16.' in line['ip_dst']: continue
            if '10.0.' in line['ip_dst']: continue
            #Filter old checks
            if line['ip_dst'] in self.ignore and self.ignore[line['ip_dst']] > int(datetime.now().timestamp()): continue
            #Filter double entries
            if line['ip_dst'] in ips: continue
            ips.append(line['ip_dst'])
            #Filter ASN if loadBalancing is disabled
            asndata = self.asndb.lookup(line['ip_dst'])
            force = False
            if asndata[0] is not None:
                asn = str(asndata[0])
                group = self.checkASNGroup(asn)
                if group != False and self.config['ASNGroups'][group['asns']]['loadBalancing'] == False and group['asns'] in asnList and group['asns'] not in self.loadBalancing: continue
                if asn in self.config['ASN'] and self.config['ASN'][asn]['loadBalancing'] == False and asn in asnList and asn not in self.loadBalancing: continue
                if group != False:
                    asnList.append(group['asns'])
                    if group['settings']['ports'] == True:
                        #Filter ports
                        if line['port_dst'] in self.config['ignorePorts']: continue
                    #Skip if Ignore is set to true
                    if group['settings']['ignore'] == True: continue
                else:
                    asnList.append(asn)
                    if asn not in self.config['ASN'] or self.config['ASN'][asn]['ports'] == True:
                        #Filter ports
                        if line['port_dst'] in self.config['ignorePorts']: continue
                    #Skip if Ignore is set to true
                    if asn in self.config['ASN']:
                        if self.config['ASN'][asn]['ignore'] == True: continue
                        if "force" in self.config['ASN'][asn] and self.config['ASN'][asn]['force'] == True: force = True
            else:
                #Filter ports
                if line['port_dst'] in self.config['ignorePorts']: continue
            #Lets go bending
            if len(threads) <= 30: threads.append(Thread(target=self.magic, args=([line,force])))
            if line['ip_dst'] not in self.ignore: self.ignore[line['ip_dst']] = {}
            self.ignore[line['ip_dst']] = int(datetime.now().timestamp()) + random.randint(600, 1500)
            print("Launched",line['ip_dst'])
        for thread in threads:
            thread.start()
        nodeThreads = []
        for thread in threads:
            thread.join()
        for server in self.nodes:
            nodeThreads.append(Thread(target=self.checkNode, args=([server])))
        for thread in nodeThreads:
            thread.start()
        for thread in nodeThreads:
            thread.join()
        print("Saving ignore.json")
        with open(self.path+'/data/ignore.json', 'w') as f:
            json.dump(self.ignore, f)
        print("Saving loadBalancing.json")
        with open(self.path+'/data/loadBalancing.json', 'w') as f:
            json.dump(self.loadBalancing, f)

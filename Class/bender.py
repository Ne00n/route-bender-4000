from concurrent.futures import ProcessPoolExecutor as Pool
import random, logging, pyasn, time, json, re, os
from netaddr import IPNetwork, IPAddress
from multiprocessing import Queue
from datetime import datetime
from threading import Thread
from Class.tools import Tools

class Bender(Tools):
    def __init__(self,path,load=True):
        filesToLoad = {path+'/config/nodes.json':True,path+'/config/config.json':True,'/tmp/pmacct_avg.json':True,path+'/data/loadBalancing.json':False,path+'/data/history.json':False}
        logging.basicConfig(filename=f"{path}/bender.log", filemode='a', format='%(levelname)s - %(message)s',datefmt='%H:%M:%S',level=logging.DEBUG)
        self.files = {}
        if load:
            print("Loading asn")
            self.asndb = pyasn.pyasn(path+'/asn.dat')
            self.path = path
            for file,required in filesToLoad.items():
                print(f"Loading {file}")
                parts = file.split("/")
                try:
                    with open(file) as handle:
                        if "pmacct_avg" in file:
                            self.files[parts[len(parts)-1]] = handle.read()
                        else:
                            self.files[parts[len(parts)-1]] = json.loads(handle.read())
                except:
                    if required == False:
                        self.files[parts[len(parts)-1]] = {}
                    else:
                        exit(f"Failed to load {file}")

    def prepare(self):
        print("Prepare")
        base = 400
        tables = re.findall("^([0-9]+)",self.cmd('cat /etc/iproute2/rt_tables')[0], re.MULTILINE | re.DOTALL)
        inetList = re.findall("(10[0-9.]+?252\.[0-9]+)",self.cmd('ip addr show lo')[0], re.MULTILINE)
        route = self.cmd("ip rule list table BENDER all")[0]
        if not "BENDER" in route:
            self.cmd('ip rule add from 0.0.0.0/0 table BENDER')
        for server in self.files['nodes.json']:
            lastByte = re.findall("^([0-9.]+)\.([0-9]+)",server, re.MULTILINE | re.DOTALL)
            node = str(base + int(lastByte[0][1]))
            if node not in tables:
                self.cmd(["echo '"+node+" Node"+node+"' >> /etc/iproute2/rt_tables"])
            if "10.0.252."+lastByte[0][1] not in inetList:
                self.cmd("ip addr add 10.0.252."+lastByte[0][1]+"/32 dev lo")
                self.cmd('ip route flush table Node'+node)
                self.cmd('ip rule add from 10.0.252.'+lastByte[0][1]+'/32 table Node'+node)
                self.cmd('ip route add default via 10.0.251.'+lastByte[0][1]+' table Node'+node)

    def clear(self):
        print("Flushing Routing Table...")
        self.cmd('ip route flush table BENDER')

    def show(self):
        print("Routing Table")
        routes = self.cmd('ip route show table BENDER')
        del routes[len(routes) -1]
        for route in routes:
            print(route)

    @staticmethod
    def magic(payload):
        line,options,asndata,files = payload['line'],payload['options'],payload['asndata'],payload['files']
        print(f"Running {line['ip_dst']}")
        lastIP,direct = Bender.mtrIP(line['ip_dst'],options,asndata)
        if lastIP is False: return {"success":False,"msg":f"Could not optimize {line['ip_dst']}, no pingable IP found"}
        origin = line['ip_dst']
        line['ip_dst'] = lastIP
        latency,queue,outQueue,count = [],Queue(),Queue(),0
        for server in files['nodes.json']:
            queue.put({"server":server,"ip":line['ip_dst']})
        threads = [Thread(target=Bender.fpingWorker, args=(queue,outQueue,)) for _ in range(int(len(files['nodes.json']) / 3))]
        for thread in threads: thread.start()
        while len(files['nodes.json']) != count:
            while not outQueue.empty():
                data = outQueue.get()
                if data['parsed']:
                    avrg = Bender.getAvrg(data['result'])
                    latency.append([avrg,data['lastByte'][0][1]])
                    logging.debug(f"Got {avrg}ms to {data['ip']} from {data['server']}")
                else:
                    print(f"{line['ip_dst']} is not reachable via {data['server']}")
                    logging.warning(f"{line['ip_dst']} is not reachable via {data['server']}")
                count += 1
            time.sleep(0.05)
        for thread in threads:
            thread.join()
        if not latency: return
        latency.sort()
        direct = Bender.getAvrg(direct[0])
        diff = direct - float(latency[0][0])
        if diff < 2 and diff > 0 and options["force"] == False:
            return {"success":False,"msg":f"Difference less than 2ms, skipping {float(direct)} vs {float(latency[0][0])} for {line['ip_dst']}"}
        elif diff < 2 and options["force"] == False:
            return {"success":False,"msg":f"Direct route is better, keeping it for {line['ip_dst']} Lowest we got {float(latency[0][0])}ms vs {int(direct)}ms direct"}
        elif float(latency[0][0]) < int(direct) or options["force"] == True:
            suffix = "/32"
            if options['whitelist']:
                for entry in latency:
                    if int(entry[1]) in options['whitelist'] and int(entry[0]) != 65000:
                        latency[0][0] = entry[0]
                        latency[0][1] = entry[1]
                        break
            if options['blacklist']:
                for entry in latency:
                    if int(entry[1]) in options['blacklist']: continue
                    if int(entry[0]) != 65000:
                        latency[0][0] = entry[0]
                        latency[0][1] = entry[1]
                        break
            if asndata[0] is not None:
                group = Bender.checkASNGroup(files,asndata[0])
                if group != False:
                    if group['settings']['loadBalancing'] is False:
                        if group['asns'] in files['loadBalancing.json']:
                            latency[0][1] = files['loadBalancing.json'][group['asns']]
                        else:
                            files['loadBalancing.json'][group['asns']] = latency[0][1]
                    suffix = group['settings']['route']
                else:
                    suffix = options['route']
                    if options['loadBalancing'] is False:
                        if asndata[0] in files['loadBalancing.json']:
                            latency[0][1] = files['loadBalancing.json'][asndata[0]]
                        else:
                            files['loadBalancing.json'][asndata[0]] = latency[0][1]
            if suffix == "/32":
                command = f'ip route add {origin}/32 via 10.0.251.{latency[0][1]} dev vxlan1 table BENDER'
                resp = Bender.cmd(command)
            else:
                if suffix == "dyn":
                    origin = asndata[1].split("/")[0]
                    suffix = "/"+asndata[1].split("/")[1]
                else:
                    origin = '.'.join(origin.split('.')[:-1]+["0"])
                command = f'ip route add {origin+suffix} via 10.0.251.{latency[0][1]} dev vxlan1 table BENDER'
                resp = Bender.cmd(command)
        return {"success":True,"msg":f"Routed {origin} via 10.0.251{latency[0][1]} improved latency by {round(diff,1)}ms"}
        
    def checkNode(self,server):
        lastByte = re.findall("^([0-9.]+)\.([0-9]+)",server, re.MULTILINE | re.DOTALL)
        #print("Checking if","10.0.251."+lastByte[0][1],"is alive")
        direct = self.cmd('fping -c3 10.0.251.'+lastByte[0][1])[1]
        if '100%' in direct:
            routes = self.cmd('ip route show table BENDER via 10.0.251.'+lastByte[0][1])[0]
            parsed = re.findall("^([0-9.\/]+)",routes, re.MULTILINE | re.DOTALL)
            for entry in parsed:
                self.cmd('ip route del '+entry+' via 10.0.251.'+lastByte[0][1]+' dev vxlan1 table BENDER')

    def debug(self,ip):
        asndata = self.asndb.lookup(ip)
        if asndata[0] is None:
            asndata = {0:"0",1:"0.0.0.0/0"}
            options = {"force":False,"multi":False}
        else:
            options = {"force":False,"multi":True}
        print("Running fping")
        mtrIP,direct = self.mtrIP(ip,options,asndata)
        if mtrIP is False: exit()
        ip = mtrIP
        count,queue,outQueue = 0,Queue(),Queue()
        queue.put({"server":"direct","ip":ip})
        for server in self.files['nodes.json']:
            queue.put({"server":server,"ip":ip})
        threads = [Thread(target=self.fpingWorker, args=(queue,outQueue,)) for _ in range(int(len(self.files['nodes.json']) / 3))]
        for thread in threads: thread.start()
        results = {}
        while len(self.files['nodes.json'])+1 != count:
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
        print("--- Results ---")
        save = 0
        for server, latency in results.items():
            print("Got " + str(latency)+"ms" + " from " + server)
            if latency < directAvrg +2:
                if save == 0: save = directAvrg - latency
        print("--- Save ---")
        print("Theoretical save:",str(round(save,2))+"ms")
        print("--- end ---")

    def history(self,activeSubnets):
        recheck = []
        for subnet, data in list(self.files['history.json'].items()):
            #First make sure the connection is idle
            if subnet in activeSubnets: continue
            #Cooldown check
            if data['expiry'] > int(datetime.now().timestamp()): continue
            recheck.append({"subnet":subnet,"ip":data['ip'],"port":data['port']})
        return recheck

    def asnLookUp(self,asnList,line):
        options,asndata = {"loadBalancing":True,"route":"/32","ignore":False,"ports":True,"force":False,"multi":False,"whitelist":[],"blacklist":[]},None
        asndata = self.asndb.lookup(line['ip_dst'])
        #Check if the lookup was successfull
        if asndata[0] is not None:
            asn = str(asndata[0])
            group = self.checkASNGroup(self.files,asn)
            if group != False and self.files['config.json']['ASNGroups'][group['asns']]['loadBalancing'] == False and group['asns'] in asnList and group['asns'] not in self.files['loadBalancing.json']: return False,[None,None],[]
            if asn in self.files['config.json']['ASN'] and self.files['config.json']['ASN'][asn]['loadBalancing'] == False and asn in asnList and asn not in self.files['loadBalancing.json']: return False,[None,None],[]            
            if group != False:
                asnList.append(group['asns'])
                base = group['settings']
            else:
                asnList.append(asn)
                base = self.files['config.json']['ASN'][asn] if asn in self.files['config.json']['ASN'] else options
            #Check Ignore
            if base['ignore'] == True: return False,[None,None],[]
            #Filter Ports
            if base['ports'] == True:
                if line['port_dst'] in self.files['config.json']['ignorePorts']: return False,[None,None],[]
            #Check Options
            if "loadBalancing" in base: options['loadBalancing'] = base['loadBalancing']
            if "force" in base: options['force'] = base['force']
            if "multi" in base: options['multi'] = base['multi']
            if "whitelist" in base: options['whitelist'] = base['whitelist']
            if "blacklist" in base: options['blacklist'] = base['blacklist']
            options['route'] = base['route']
        else:
            #Filter ports
            if line['port_dst'] in self.files['config.json']['ignorePorts']: return False,[None,None],[]
        #Lets go bending
        return options,asndata,asnList

    def run(self):
        ips,asnList,activeSubnets,threads = [],[],[],[]
        print("Launching")
        self.prepare()
        print("Checking pmacct")
        for row in self.files['pmacct_avg.json'].split('\n'):
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
            #Filter ASN if loadBalancing... is disabled/enabled
            options,asndata,asnList = self.asnLookUp(asnList,line)
            if options == False: continue
            subnet = asndata[1] if asndata[1] is not None else f"{line['ip_dst']}/32"
            activeSubnets.append(subnet)
            #Skip if already in history
            if subnet in self.files['history.json']: continue
            #Check if route for IP already exists
            route = self.cmd("ip r get "+line['ip_dst'])[0]
            if 'vxlan1' in route:
                print(line['ip_dst'],"route already exists")
                logging.info(line['ip_dst'],"route already exists")
                continue
            #Limit of current checks, to keep cpu load in okay levels to prevent lags
            if len(threads) <= self.files['config.json']['threads']:
                #Add to History 
                if subnet not in self.files['history.json']: self.files['history.json'][subnet] = {}
                self.files['history.json'][subnet] = {'ip':line['ip_dst'],'port':line['port_dst'],'expiry':int(datetime.now().timestamp()) + random.randint(3600, 14400)} #wait 1-4 hours before re-check
                threads.append({"line":line,"options":options,"asndata":asndata,"files":self.files})
                print("Adding",line['ip_dst'])
        history = self.history(activeSubnets)
        print("Checking history")
        for data in history:
            if len(threads) > self.files['config.json']['threads']: break
            #Filter ASN if loadBalancing... is disabled/enabled
            line = {"ip_dst":data['ip'],"port_dst":data['port']}
            options,asndata,asnList = self.asnLookUp(asnList,line)
            if options == False: continue
            #Check for existing route
            route = self.cmd(f"ip r get {data['ip']}")[0]
            if 'vxlan1' in route:
                #Remove the route if re-check is scheduled
                node = parsed = re.findall("via ([0-9.]+)",route, re.MULTILINE | re.DOTALL)[0]
                routes = self.cmd(f'ip route show table BENDER via {node}')[0]
                parsed = re.findall("^([0-9.\/]+)",routes, re.MULTILINE | re.DOTALL)
                for entry in parsed:
                    if IPAddress(data['ip']) in IPNetwork(entry):
                        print(f"Removing {entry} from history.json")
                        logging.info(f"Removing {entry} from history.json")
                        self.cmd(f'ip route del {entry} via {node} dev vxlan1 table BENDER')
                        break
            self.files['history.json'][data['subnet']]['expiry'] = int(datetime.now().timestamp()) + random.randint(7200, 21600) #wait 2-6 hours before re-check
            threads.append({"line":line,"options":options,"asndata":asndata,"files":self.files})
            print("Adding",data['ip'])

        #dispatch
        pool = Pool(max_workers = self.files['config.json']['threads'])
        results = pool.map(self.magic, threads)
        #wait for everything
        pool.shutdown(wait=True)
        #process results
        print("Getting Results")
        for result in results:
            print(result['msg'])
            logging.info(result['msg'])
        #check nodes
        print("Checking Nodes")
        nodeThreads = []
        for server in self.files['nodes.json']:
            nodeThreads.append(Thread(target=self.checkNode, args=([server])))
        for thread in nodeThreads: thread.start()
        for thread in nodeThreads: thread.join()
        #updating json files
        saving = ['loadBalancing.json','history.json']
        for entry in saving:
            print(f"Saving {entry}")
            with open(self.path+f'/data/{entry}', 'w') as f:
                json.dump(self.files[entry], f)

from concurrent.futures import ProcessPoolExecutor as Pool
import random, logging, pyasn, time, json, sys, re, os
from logging.handlers import RotatingFileHandler
from netaddr import IPNetwork, IPAddress
from ipaddress import ip_network
from datetime import datetime
from Class.tools import Tools
import multiprocessing

class Bender(Tools):
    def __init__(self,path,load=True,level="info"):
        #logging
        levels = {
            'critical': logging.CRITICAL,
            'error': logging.ERROR,
            'warning': logging.WARNING,
            'info': logging.INFO,
            'debug': logging.DEBUG
        }
        stream_handler = logging.StreamHandler()
        stream_handler.setLevel(levels[level])
        logging.basicConfig(format='%(asctime)s %(levelname)s %(message)s',datefmt='%H:%M:%S',level=levels[level],handlers=[RotatingFileHandler(maxBytes=10000000,backupCount=5,filename=f"{path}/logs/bender.log"),stream_handler])
        #Files
        filesToLoad = {path+'/config/nodes.json':True,path+'/config/config.json':True,'/tmp/pmacct_avg.json':True,path+'/data/loadBalancing.json':False,path+'/data/history.json':False}
        self.files = {}
        os.nice(20)
        if load:
            logging.debug("Loading asn")
            self.asndb = pyasn.pyasn(path+'/asn.dat')
            self.path = path
            for file,required in filesToLoad.items():
                logging.debug(f"Loading {file}")
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
        os.nice(0)

    def prepare(self):
        logging.debug("Prepare")
        base = 400
        tables = re.findall("^([0-9]+)",self.cmd('cat /etc/iproute2/rt_tables')[0], re.MULTILINE | re.DOTALL)
        inetList = re.findall("(10[0-9.]+?252\.[0-9]+)",self.cmd('ip addr show lo')[0], re.MULTILINE)
        route = self.cmd("ip rule list table BENDER all")[0]
        if not "BENDER" in route:
            self.cmd('ip rule add from 0.0.0.0/0 table BENDER')
            self.cmd('ip -6 rule add from ::/0 table BENDER')
        for server in self.files['nodes.json']:
            lastByte = re.findall("^([0-9.]+)\.([0-9]+)",server, re.MULTILINE | re.DOTALL)
            node = str(base + int(lastByte[0][1]))
            if node not in tables:
                self.cmd(["echo '"+node+" Node"+node+"' >> /etc/iproute2/rt_tables"])
            if "10.0.252."+lastByte[0][1] not in inetList:
                self.cmd(f'ip addr add 10.0.252.{lastByte[0][1]}/32 dev lo')
                self.cmd(f'ip -6 addr add fc10:252::{lastByte[0][1]}/128 dev lo')
                self.cmd(f'ip rule add from 10.0.252.{lastByte[0][1]}/32 table Node{node}')
                self.cmd(f'ip -6 rule add from fc10:252::{lastByte[0][1]}/128 table Node{node}')
                self.cmd(f'ip route add default via 10.0.251.{lastByte[0][1]} table Node{node}')
                self.cmd(f'ip -6 route add default via fc10:251::{lastByte[0][1]} table Node{node}')

    def clear(self):
        print("Flushing Routing Table...")
        self.cmd('ip route flush table BENDER')
        self.cmd('ip -6 route flush table BENDER')

    def show(self):
        print("Routing Table")
        routes = self.cmd('ip route show table BENDER')
        del routes[len(routes) -1]
        for route in routes:
            print(route)

    def stats(self):
        print("Stats")
        routes = self.cmd('ip route show table BENDER')[0]
        routes = routes.splitlines()
        data = {}
        for route in routes:
            parsed = re.findall("^([0-9.\/]+)",route, re.MULTILINE | re.DOTALL)
            line = {"ip_dst":parsed[0].split("/")[0],"port_dst":0}
            options,asndata,asnList = self.asnLookUp([],line)
            if asndata[0] is not None:
                if not asndata[0] in data: data[asndata[0]] = {"count":0,"options":{}}
                data[asndata[0]]['count'] += 1
                data[asndata[0]]['options'] = options
            else:
                data['unknown']['count'] += 1
        data = sorted(data.items(), key=lambda item: int(item[1]['count']), reverse=True)
        result = []
        result.append("ASN\tEntries\tPercentage\tRoute")
        result.append("-------\t-------\t-------\t-------")
        for asn in data:
            result.append(f"{asn[0]}\t{asn[1]['count']}\t{round(100 / len(routes) * asn[1]['count'],1)}%\t{asn[1]['options']['route']}")
        print(Bender.formatTable(result))

    def optimize(self,target,port):
        line = {"ip_dst":target,"port_dst":port}
        options,asndata,asnList = self.asnLookUp([],line)
        if options == False: exit("Options empty")
        print(f"Subnet {options['subnet']}")
        #Skip if already in history
        if options['subnet'] in self.files['history.json']: 
            print(self.files['history.json'][options['subnet']])
            exit("Subnet already in history.json")
        #Check if route for IP already exists
        route = self.cmd("ip r get "+line['ip_dst'])[0]
        if 'vxlan1' in route: exit(f"{line['ip_dst']} route already exists")
        payload = {"subnet":options['subnet'],"line":line,"options":options,"asndata":asndata,"files":self.files}
        #Optimize
        result = self.magic(payload)
        print(result['msg'])

    @staticmethod
    def magic(payload):
        line,options,asndata,files,subnet,lbMap = payload['line'],payload['options'],payload['asndata'],payload['files'],payload['subnet'],{}
        logging.debug(f"Running {line['ip_dst']}")
        pingable,srcFping = Bender.mtrIP(line['ip_dst'],options,asndata)
        if pingable == "0.0.0.0": return {"lbMap":lbMap,"success":False,"possible":False,"line":line,"subnet":subnet,"msg":f"Could not optimize {line['ip_dst']}, no pingable IP found"}
        #fping
        threads,latency = [],[]
        for server in files['nodes.json']: threads.append({"server":server,"ip":pingable})
        #dispatch
        pool = multiprocessing.Pool(processes = int(len(files['nodes.json']) / 3))
        results = pool.map(Bender.fpingWorker, threads)
        #wait for everything
        pool.close()
        pool.join()
        #process results
        for data in results: 
            if data['parsed']:
                avrg = Bender.getAvrg(data['result'])
                latency.append([avrg,data['lastByte'][0][1]])
                logging.debug(f"Got {avrg}ms to {data['ip']} from {data['server']}")
            else:
                logging.warning(f"{pingable} is not reachable via {data['server']}")
        #if we got no result abort       
        if not latency: return
        latency.sort()
        direct = Bender.getAvrg(srcFping)
        #whitelist / blacklist
        for entry in latency:
            #when exit in blacklist continue
            if int(entry[1]) in options['blacklist']: continue
            if int(entry[0]) != 65000 and (int(entry[1]) in options['whitelist'] or options['blacklist'] and int(entry[1]) not in options['blacklist']):
                #push it to the top
                latency[0][0] = entry[0]
                latency[0][1] = entry[1]
                break
        #Load Balancing
        if asndata[0] is not None:
            group = Bender.checkASNGroup(files,asndata[0])
            lbSettings = group['settings'] if group else options
            lbASN = group['asns'] if group else asndata[0]
            if lbSettings['loadBalancing'] is False:
                if lbASN in files['loadBalancing.json']:
                    latency[0][1] = files['loadBalancing.json'][lbASN]
                else:
                    lbMap[lbASN] = latency[0][1]
        diff = direct - float(latency[0][0])
        if diff < 2 and diff > 0 and options["force"] == False:
            return {"lbMap":lbMap,"success":False,"possible":True,"line":line,"subnet":subnet,"msg":f"Difference less than 2ms, skipping {float(direct)} vs {float(latency[0][0])} for {line['ip_dst']}"}
        elif diff < 2 and options["force"] == False:
            return {"lbMap":lbMap,"success":False,"possible":True,"line":line,"subnet":subnet,"msg":f"Direct route is better, keeping it for {line['ip_dst']} Lowest we got {float(latency[0][0])}ms vs {int(direct)}ms direct"}
        elif float(latency[0][0]) < int(direct) or options["force"] == True:
            #Run
            if IPNetwork(subnet).version == 4:
                dest = f"10.0.251.{latency[0][1]}"
                Bender.cmd(f'ip route add {subnet} via {dest} dev vxlan1 table BENDER')
            else:
                dest = f"fc10:251::{latency[0][1]}"
                Bender.cmd(f'ip -6 route add {subnet} via {dest} dev vxlan1v6 table BENDER')
        return {"lbMap":lbMap,"success":True,"possible":True,"line":line,"subnet":subnet,"msg":f"Routed {line['ip_dst']} ({subnet}) via {dest} improved latency by {round(diff,1)}ms"}
        
    @staticmethod
    def checkNode(server):
        lastByte = re.findall("^([0-9.]+)\.([0-9]+)",server, re.MULTILINE | re.DOTALL)
        direct = Bender.cmd('fping -c3 10.0.251.'+lastByte[0][1])[1]
        subnets = []
        if '100%' in direct:
            logging.debug(direct)
            logging.warning(f"10.0.251.{lastByte[0][1]} is down, removing routes")
            #IPv4
            routes = Bender.cmd('ip route show table BENDER via 10.0.251.'+lastByte[0][1])[0]
            parsed = re.findall("^([0-9.\/]+)",routes, re.MULTILINE | re.DOTALL)
            for entry in parsed:
                logging.debug(f"Removing {entry} from routing table")
                Bender.cmd(f'ip route del {entry} via 10.0.251.{lastByte[0][1]} dev vxlan1 table BENDER')
                logging.debug(f"Removing {entry} from history.json")
                subnets.append(entry)
            #IPv6
            routes = Bender.cmd(f'ip -6 route show table BENDER via fc10:251::{lastByte[0][1]}')[0]
            parsed = re.findall("^([a-z0-9:.\/]+)",routes, re.MULTILINE | re.DOTALL)
            for entry in parsed:
                logging.debug(f"Removing {entry} from routing table")
                Bender.cmd(f'ip -6 route del {entry} via fc10:251::{lastByte[0][1]} dev vxlan1v6 table BENDER')
                logging.debug(f"Removing {entry} from history.json")
                subnets.append(entry)
        return subnets

    def debug(self,ip):
        asndata = self.asndb.lookup(ip)
        if asndata[0] is None:
            asndata = {0:"0",1:"0.0.0.0/0"}
            options = {"force":False,"multi":False,"route":"/32"}
        else:
            options = {"force":False,"multi":True,"route":"/32"}
        print("Running fping")
        pingable,srcFping = self.mtrIP(ip,options,asndata)
        if pingable == "0.0.0.0": exit()
        ip = pingable
        #fping
        threads,fping = [],{}
        threads.append({"server":"direct","ip":ip})
        for server in self.files['nodes.json']: threads.append({"server":server,"ip":ip})
        #dispatch
        pool = multiprocessing.Pool(processes = int(len(self.files['nodes.json']) / 3))
        results = pool.map(self.fpingWorker, threads)
        #wait for everything
        pool.close()
        pool.join()
        #process results
        for data in results: 
            if data['parsed']:
                fping[data['server']] = self.getAvrg(data['result'])
            else:
                print(data['ip']+" is not reachable via "+data['server'])
        fping = {k: fping[k] for k in sorted(fping, key=fping.get)}
        print("--- Direct ---")
        directAvrg = fping["direct"]
        print("Got " + str(directAvrg) +"ms direct")
        del fping["direct"]
        print("--- Results ---")
        save = 0
        for server, latency in fping.items():
            print("Got " + str(latency)+"ms" + " from " + server)
            if latency < directAvrg +2:
                if save == 0: save = directAvrg - latency
        print("--- Save ---")
        print("Theoretical save:",str(round(save,2))+"ms")
        print("--- end ---")

    def history(self,activeSubnets):
        recheck = []
        for subnet, data in list(self.files['history.json'].items()):
            #Reduce re-check of active connections to 15 minutes
            deadline = int(datetime.now().timestamp()) + 900
            #If the re-check planned in more than 15 minutes, reschedule
            if subnet in activeSubnets and data['expiry'] > deadline:
                logging.debug(f"Rescheduled {subnet}")
                self.files['history.json'][subnet]['expiry'] = deadline
            #First make sure the connection is idle
            if subnet in activeSubnets: continue
            #Cooldown check
            if data['expiry'] > int(datetime.now().timestamp()): continue
            recheck.append({"subnet":subnet,"ip":data['ip'],"port":data['port']})
        return recheck

    def asnLookUp(self,asnList,line):
        options,asndata = {"loadBalancing":True,"route":"/24","ignore":False,"ports":True,"force":False,"multi":False,"whitelist":[],"blacklist":[],"subnet":""},None
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
            if not "loadBalancing" in base: base['loadBalancing'] = True
            if not "force" in base: base['force'] = False
            if not "multi" in base: base['multi'] = False
            if not "whitelist" in base: base['whitelist'] = []
            if not "blacklist" in base: base['blacklist'] = []
            if not "route" in base: base['route'] = "/24"
            #Subnet
            if base['route'] == "/32":
                base['subnet'] = f"{line['ip_dst']}/32" if IPAddress(line['ip_dst']).version == 4 else f"{line['ip_dst']}/128"
            elif base['route'] == "/24":
                tmpIP = '.'.join(line['ip_dst'].split('.')[:-1])
                base['subnet'] = f"{tmpIP}.0/24" if IPAddress(line['ip_dst']).version == 4 else str(ip_network(f"{line['ip_dst']}/128").supernet(new_prefix=48))
            elif base['route'] == "dyn":
                base['subnet'] = asndata[1]
        else:
            #load options
            base = options
            #Filter ports
            if line['port_dst'] in self.files['config.json']['ignorePorts']: return False,[None,None],[]
            #Subnet
            base['subnet'] = f"{line['ip_dst']}/24" if IPAddress(line['ip_dst']).version == 4 else str(ip_network(f"{line['ip_dst']}/128").supernet(new_prefix=48))
        #Lets go bending
        return base,asndata,asnList

    def run(self):
        ips,asnList,activeSubnets,threads = [],[],[],[]
        running = self.cmd('ps ax | grep "bender.py"')[0]
        if len(running.split("\n")) > 4:
            logging.warning("bender.py already running, exiting")
            exit("bender.py already running, exiting")
        logging.debug("Launching")
        self.prepare()
        logging.debug("Checking pmacct")
        for row in self.files['pmacct_avg.json'].split('\n'):
            if row.strip() == "": continue
            line = json.loads(row)
            #Filter Local/Multicast traffic
            if '239.255.255.' in line['ip_dst']: continue
            if '224.0.0.' in line['ip_dst']: continue
            if '192.168.' in line['ip_dst']: continue
            if '172.16.' in line['ip_dst']: continue
            if '10.0.' in line['ip_dst']: continue
            #Filter out private ranges
            if IPAddress(line['ip_dst']).is_private(): continue
            #Filter out reserved ranges
            if IPAddress(line['ip_dst']).is_reserved(): continue
            #Filter double entries
            if line['ip_dst'] in ips: continue
            ips.append(line['ip_dst'])
            #Filter ASN if loadBalancing... is disabled/enabled
            options,asndata,asnList = self.asnLookUp(asnList,line)
            #if ignored = True or ports in ignorePorts
            if options == False: continue
            #tracking active subnets, preventing re-optimizing active links
            activeSubnets.append(options['subnet'])
            #Skip if already in history
            if options['subnet'] in self.files['history.json']: continue
            #Skip if listed in ignoreSubnets
            if options['subnet'] in self.files['config.json']['ignoreSubnets']: continue
            #Check if route for IP already exists
            route = self.cmd("ip r get "+line['ip_dst'])[0]
            if 'vxlan1' in route:
                logging.info(f"{line['ip_dst']} route already exists")
                continue
            #Limit of current checks, to keep cpu load in okay levels to prevent lags
            if len(threads) <= self.files['config.json']['threads']:
                threads.append({"subnet":options['subnet'],"line":line,"options":options,"asndata":asndata,"files":self.files})
                logging.info(f"Analyzing {line['ip_dst']}")
        history = self.history(activeSubnets)
        logging.debug("Checking history")
        for data in history:
            #Check if we already hit the current checks limit
            if len(threads) > self.files['config.json']['threads']: break
            #Filter ASN if loadBalancing... is disabled/enabled
            line = {"ip_dst":data['ip'],"port_dst":data['port']}
            options,asndata,asnList = self.asnLookUp(asnList,line)
            if options == False: continue
            #Check for existing route
            route = self.cmd(f"ip r get {data['ip']}")[0]
            if 'vxlan1' in route:
                #Get Exit from IP
                node = parsed = re.findall("via ([a-z0-9:.]+)",route, re.MULTILINE | re.DOTALL)[0]
                #Get all Subnets from Exit
                ex = "ip" if IPAddress(data['ip']).version == 4 else "ip -6"
                routes = self.cmd(f'{ex} route show table BENDER via {node}')[0]
                #Parse all Subnets
                parsed = re.findall("^([a-z0-9:.\/]+)",routes, re.MULTILINE | re.DOTALL)
                for entry in parsed:
                    #Find correct route/subnet
                    if IPAddress(data['ip']) in IPNetwork(entry):
                        #Remove the subnet if re-check is scheduled
                        logging.info(f"Removing {entry} from routing table")
                        vxlan = "vxlan1" if IPAddress(data['ip']).version == 4 else "vxlan1v6"
                        self.cmd(f'ip route del {entry} via {node} dev {vxlan} table BENDER')
                        #Remove from history.json
                        logging.debug(f"Removing {data['subnet']} from history.json")
                        if entry in self.files['history.json']: del self.files['history.json'][data['subnet']]
                        break
            threads.append({"subnet":options['subnet'],"line":line,"options":options,"asndata":asndata,"files":self.files})
            logging.info(f"Analyzing {data['ip']}")
        #dispatch
        pool = Pool(max_workers = self.files['config.json']['threads'])
        results = pool.map(self.magic, threads)
        #wait for everything
        pool.shutdown(wait=True)
        #process results
        for result in results:
            logging.info(result['msg'])
            if result['subnet'] not in self.files['history.json']: self.files['history.json'][result['subnet']] = {}
            if result['possible'] == True and result['success'] == False:
                #wait 4-8 hours before re-check, latency difference wasn't high enough or direct was better
                self.files['history.json'][result['subnet']] = {'ip':result['line']['ip_dst'],'port':result['line']['port_dst'],'expiry':int(datetime.now().timestamp()) + random.randint(14400, 28800)}
            elif result['possible'] == False:
                #wait 12-24 hours before re-check, since we could not optimize / no pingable ip
                self.files['history.json'][result['subnet']] = {'ip':result['line']['ip_dst'],'port':result['line']['port_dst'],'expiry':int(datetime.now().timestamp()) + random.randint(43200, 86400)}
            else:
                #wait 2-6 hours before re-check
                self.files['history.json'][result['subnet']] = {'ip':result['line']['ip_dst'],'port':result['line']['port_dst'],'expiry':int(datetime.now().timestamp()) + random.randint(7200, 21600)}
            #loadbalancing
            if result['lbMap']:
                for asn,node in result['lbMap'].items():
                    self.files['loadBalancing.json'][asn] = node
        #check nodes
        logging.debug("Checking Nodes")
        nodeThreads,online = [],0
        for server in self.files['nodes.json']: nodeThreads.append(server)
        #dispatch
        pool = multiprocessing.Pool(processes = len(nodeThreads))
        results = pool.map(self.checkNode, nodeThreads)
        #wait for everything
        pool.close()
        pool.join()
        #process results
        for response in results:
            #when the list is empty = online 
            if not response: 
                online += 1
            else:
                for subnet in response:
                    if subnet in self.files['history.json']: del self.files['history.json'][subnet]
        logging.debug(f"Status {online}/{len(nodeThreads)} online")
        #updating json files
        saving = ['loadBalancing.json','history.json']
        for entry in saving:
            logging.debug(f"Saving {entry}")
            with open(self.path+f'/data/{entry}', 'w') as f:
                json.dump(self.files[entry], f)
        logging.debug("Done")

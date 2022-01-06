import subprocess, random, pyasn, time, json, re, os
from multiprocessing import Queue
from datetime import datetime
from threading import Thread

class Bender:
    def __init__(self,path,load=True):
        filesToLoad = {path+'/config/nodes.json':True,path+'/config/config.json':True,'/tmp/pmacct_avg.json':True,path+'/data/ignore.json':False,path+'/data/loadBalancing.json':False,path+'/data/history.json':False}
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

    def cmd(self,cmd):
        p = subprocess.run(cmd, stdin=None, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
        return [p.stdout.decode('utf-8'),p.stderr.decode('utf-8')]

    def clear(self):
        print("Flushing Routing Table...")
        self.cmd('ip route flush table BENDER')

    def show(self):
        print("Routing Table")
        routes = self.cmd('ip route show table BENDER')
        del routes[len(routes) -1]
        for route in routes:
            print(route)

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
        while queue.qsize() > 0:
            try:
                data = queue.get_nowait()
                parsed,result,lastByte = self.fpingSource(data['server'],data['ip'])
                outQueue.put({"parsed":parsed,"result":result,"lastByte":lastByte,"ip":data['ip'],"server":data['server']})
            except Exception as e:
                return True

    def magic(self,line,options,asndata):
        origin = 0
        lastIP,direct = self.mtrIP(line['ip_dst'],options,asndata)
        if lastIP is False: exit()
        origin = line['ip_dst']
        line['ip_dst'] = lastIP
        latency,queue,outQueue,count = [],Queue(),Queue(),0
        for server in self.files['nodes.json']:
            queue.put({"server":server,"ip":line['ip_dst']})
        threads = [Thread(target=self.fpingWorker, args=(queue,outQueue,)) for _ in range(int(len(self.files['nodes.json']) / 3))]
        for thread in threads: thread.start()
        while len(self.files['nodes.json']) != count:
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
        if diff < 2 and diff > 0 and options["force"] == False:
            print("Difference less than 2ms, skipping",float(direct),"vs",float(latency[0][0]),"for",line['ip_dst'])
        elif diff < 2 and options["force"] == False:
            print("Direct route is better, keeping it for",line['ip_dst'],"Lowest we got",float(latency[0][0]),"ms vs",int(direct),"ms direct")
        elif float(latency[0][0]) < int(direct) or options["force"] == True:
            if origin == 0: origin = line['ip_dst']
            suffix = "/32"
            if asndata[0] is not None:
                group = self.checkASNGroup(asndata[0])
                if group != False:
                    if group['settings']['loadBalancing'] is False:
                        if group['asns'] in self.files['loadBalancing.json']:
                            latency[0][1] = self.files['loadBalancing.json'][group['asns']]
                        else:
                            self.files['loadBalancing.json'][group['asns']] = latency[0][1]
                    suffix = group['settings']['route']
                else:
                    for asn,settings in self.files['config.json']['ASN'].items():
                        if int(asn) == int(asndata[0]):
                            suffix = settings['route']
                            if self.files['config.json']['ASN'][asn]['loadBalancing'] is False:
                                if asn in self.files['loadBalancing.json']:
                                    latency[0][1] = self.files['loadBalancing.json'][asn]
                                else:
                                    self.files['loadBalancing.json'][asn] = latency[0][1]
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
            parsed = re.findall("^([0-9.\/]+)",routes, re.MULTILINE | re.DOTALL)
            for entry in parsed:
                self.cmd('ip route del '+entry+' via 10.0.251.'+lastByte[0][1]+' dev vxlan1 table BENDER')

    def checkASNGroup(self,asn):
        for asnsRaw,settings in self.files['config.json']['ASNGroups'].items():
            asns = asnsRaw.split(",")
            if str(asn) in asns:
                return {"asns":asnsRaw,"settings":settings}
                break
        return False

    def mtrIP(self,target,options,asndata):
        orgTarget = target
        if asndata[0] is not None and options["multi"] == True:
            ips = [1,2,3,252,253,254]
            ip,sub = asndata[1].split("/")
            target += " "+ip
            for entry in ips: target += f" {ip[:-1]}{entry}"
        direct = self.cmd("fping -c6 "+target)
        if asndata[0] is not None and options["multi"] == True:
            results = direct[1].split("\n")
            for result in results:
                if "/0%" in result:
                    target = re.findall("[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+",result, re.MULTILINE)[0]
                    break
            split = target.split(" ")
            if len(split) > 1: target = orgTarget
            latency = direct[0].split("\n")
            direct[0] = ""
            for result in latency:
                if target in result: direct[0] += result+"\n"
            tmp = direct[1].split("\n")
            direct[1] = ""
            for result in tmp:
                if target in result: direct[1] +=result+"\n"
        if '100%' in direct[1]:
            print(target,"not reachable, trying to MTR")
            result = self.cmd('mtr '+target+' --report --report-cycles 4 --no-dns')
            parsed = re.findall("-- ([0-9.]+)",result[0], re.MULTILINE)
            for run in range(1,3):
                lastIP = parsed[len(parsed) - run]
                if self.isPrivate(lastIP):
                    print(lastIP+" is private, skipping")
                    return False,False
                if lastIP != "???":
                    direct = self.cmd("fping -c6 "+lastIP)
                if '100%' in direct[1]:
                    print(target,"("+lastIP+") not reachable.")
                else:
                    return lastIP,direct
                if run == 2:
                    print("Could not find pingable IP for",target)
                    return False,False
        return target,direct

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
        print("--- Top 5 ---")
        save,count = 0,0
        for server, latency in results.items():
            if count < 5: print("Got " + str(latency)+"ms" + " from " + server)
            if latency < directAvrg +2:
                if save == 0: save = directAvrg - latency
            count += 1
        print("--- Save ---")
        print("Theoretical save:",str(round(save,2))+"ms")
        print("--- end ---")

    def cleanIgnore(self):
        for target, expiry in list(self.files['ignore.json'].items()):
            if int(datetime.now().timestamp()) > expiry: 
                print(f"Removing {target} from ignore.json")
                del self.files['ignore.json'][target]

    def history(self,activeSubnets):
        recheck = []
        #if self.files['history.json'] == {}: return recheck
        for subnet, data in list(self.files['history.json'].items()):
            #First make sure the connection is idle
            if subnet in activeSubnets: continue
            #Cooldown check
            if data['expiry'] > int(datetime.now().timestamp()): continue
            recheck.append({"subnet":subnet,"ip":data['ip'],"port":data['port']})
        return recheck

    def asnLookUp(self,asnList,line):
        options,asndata = {"force":False,"multi":False},None
        asndata = self.asndb.lookup(line['ip_dst'])
        force,multi = False,False
        if asndata[0] is not None:
            asn = str(asndata[0])
            group = self.checkASNGroup(asn)
            if group != False and self.files['config.json']['ASNGroups'][group['asns']]['loadBalancing'] == False and group['asns'] in asnList and group['asns'] not in self.files['loadBalancing.json']: return options,asndata,asnList
            if asn in self.files['config.json']['ASN'] and self.files['config.json']['ASN'][asn]['loadBalancing'] == False and asn in asnList and asn not in self.files['loadBalancing.json']: return options,asndata,asnList
            if group != False:
                asnList.append(group['asns'])
                if group['settings']['ports'] == True:
                    #Filter ports
                    if line['port_dst'] in self.files['config.json']['ignorePorts']: return options,asndata,asnList
                #Skip if Ignore is set to true
                if group['settings']['ignore'] == True: return options,asndata,asnList
                if "force" in group['settings'] and group['settings']['force'] == True: force = True
                if "multi" in group['settings'] and group['settings']['multi'] == True: multi = True
            else:
                asnList.append(asn)
                if asn not in self.files['config.json']['ASN'] or self.files['config.json']['ASN'][asn]['ports'] == True:
                    #Filter ports
                    if line['port_dst'] in self.files['config.json']['ignorePorts']: return options,asndata,asnList
                #Skip if Ignore is set to true
                if asn in self.files['config.json']['ASN']:
                    if self.files['config.json']['ASN'][asn]['ignore'] == True: return options,asndata
                    if "force" in self.files['config.json']['ASN'][asn] and self.files['config.json']['ASN'][asn]['force'] == True: force = True
                    if "multi" in self.files['config.json']['ASN'][asn] and self.files['config.json']['ASN'][asn]['multi'] == True: multi = True
        else:
            #Filter ports
            if line['port_dst'] in self.files['config.json']['ignorePorts']: return options,asndata,asnList
        #Lets go bending
        options = {"force":force,"multi":multi}
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
            subnet = asndata[1] if asndata[1] is not None else f"{line['ip_dst']}/32"
            activeSubnets.append(subnet)
            #Check if route for IP already exists
            route = self.cmd("ip r get "+line['ip_dst'])[0]
            if 'vxlan1' in route:
                print(line['ip_dst'],"route already exists")
                continue
            #Filter out old expired ignores
            self.cleanIgnore()
            #Filter old checks
            if subnet in self.files['ignore.json']:
                if self.files['ignore.json'][subnet] > int(datetime.now().timestamp()): 
                    #If we checked the IP but did not bend it and the connection is still active, we extend the ignore to prevent sudden bending syndrom
                    self.files['ignore.json'][subnet] = self.files['ignore.json'][subnet] + 60
                    continue
            #Limit of current checks, to keep cpu load in okay levels to prevent lags
            if len(threads) <= 30:
                #Add to History 
                if subnet not in self.files['history.json']: self.files['history.json'][subnet] = {}
                self.files['history.json'][subnet] = {'ip':line['ip_dst'],'port':line['port_dst'],'expiry':int(datetime.now().timestamp()) + random.randint(3600, 14400)} #wait 1-4 hours before re-check
                #Add to Ignore
                self.files['ignore.json'][subnet] = int(datetime.now().timestamp()) + random.randint(1800, 5400) #ignore for 30-90 minutes
                threads.append(Thread(target=self.magic, args=([line,options,asndata])))
                print("Launched",line['ip_dst'])
        history = self.history(activeSubnets)
        print("Checking history")
        for data in history:
            if len(threads) > 30: break
            route = self.cmd(f"ip r get {data['ip']}")[0]
            if 'vxlan1' in route:
                #Remove the route if re-check is scheduled
                node = parsed = re.findall("via ([0-9.]+)",route, re.MULTILINE | re.DOTALL)[0]
                routes = self.cmd(f'ip route show table BENDER via {node}')[0]
                parsed = re.findall("^([0-9.\/]+)",routes, re.MULTILINE | re.DOTALL)
                for entry in parsed:
                    if entry == data['subnet']:
                        print(f"Removing {entry} from history.json")
                        self.cmd(f'ip route del {entry} via {node} dev vxlan1 table BENDER')
                        break
            self.files['history.json'][data['subnet']]['expiry'] = int(datetime.now().timestamp()) + random.randint(7200, 21600) #wait 2-6 hours before re-check
            self.files['ignore.json'][data['subnet']] = int(datetime.now().timestamp()) + random.randint(1800, 5400) #ignore for 30-90 minutes
            #Filter ASN if loadBalancing... is disabled/enabled
            line = {"ip_dst":data['ip'],"port_dst":data['port']}
            options,asndata,asnList = self.asnLookUp(asnList,line)
            threads.append(Thread(target=self.magic, args=([line,options,asndata])))
            print("Launched",data['ip'])

        for thread in threads: thread.start()
        for thread in threads: thread.join()
        nodeThreads = []
        for server in self.files['nodes.json']:
            nodeThreads.append(Thread(target=self.checkNode, args=([server])))
        for thread in nodeThreads: thread.start()
        for thread in nodeThreads: thread.join()
        saving = ['ignore.json','loadBalancing.json','history.json']
        for entry in saving:
            print(f"Saving {entry}")
            with open(self.path+f'/data/{entry}', 'w') as f:
                json.dump(self.files[entry], f)

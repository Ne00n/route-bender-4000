import subprocess, logging, re, os
from netaddr import IPAddress
import importlib.util

class Tools:

    path = os.path.dirname(os.path.realpath(__file__))
    path = path.replace("Class","Plugins")
    plugins = os.listdir(path)
    pluginsToLoad = []
    for filename in plugins:
        if not filename.endswith(".py"): continue
        plugin = filename.replace(".py","")
        pluginsToLoad.append(plugin)
    plugins = {}
    for plugin in pluginsToLoad:
        spec = importlib.util.spec_from_file_location(plugin, f"{path}/{plugin}.py")
        tmpPlugin = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tmpPlugin)
        plugins[plugin] = tmpPlugin

    @staticmethod
    def cmd(cmd):
        p = subprocess.run(cmd, stdin=None, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
        return [p.stdout.decode('utf-8'),p.stderr.decode('utf-8')]

    @staticmethod
    def hook(event,target=""):
        for plugin in Tools.plugins:
            tmpPlugin = getattr(Tools.plugins[plugin], plugin)
            result = getattr(tmpPlugin, event)(tmpPlugin,target)
            return result
        return False

    @staticmethod
    def fping(targets,pings=3,cmd="fping -c"):
        fping = f"{cmd}{pings} "
        fping += " ".join(targets)
        result = Tools.cmd(fping)[0]
        parsed = re.findall("([0-9.]+).*?([0-9]+.[0-9]+|timed out).*?([0-9]+)% loss",result, re.MULTILINE)
        if not parsed: return False
        latency =  {}
        for ip,ms,loss in parsed:
            if ip not in latency: latency[ip] = []
            latency[ip].append([ms,loss])
        return latency
    
    @staticmethod
    def mtrIP(target,options,asndata):
        targets = [target]
        if asndata[0] is not None and options["multi"] == True and options['route'] != "/32":
            logging.debug(f"ASN {asndata[0]} {target} multi")
            ips4,ips6 = [0,1,2,3,4,5,252,253,254],['','1']
            ip,prefix = options['subnet'].split("/")
            ips = ips4 if IPAddress(target).version == 4 else ips6
            for entry in ips:
                host = f" {ip[:-1]}{entry}" if IPAddress(ip).version == 4 else f" {ip}{entry}"
                targets.append(host)
        results = Tools.fping(targets)
        avg = Tools.getAvrg(results[target])
        if avg != 65000: return target, avg
        data = Tools.hook('unreachable',target)
        if data:
            results = Tools.fping(data)
            latency = Tools.getAvrgAll(results)
            first = next(iter(latency))
            if latency[first] != 65000: return first,latency[first]
        logging.debug(f"{target} not reachable, trying to MTR")
        mtr = Tools.cmd('mtr '+target+' --report --report-cycles 3 --no-dns')
        ips = re.findall("-- ([0-9a-z.:]+)",mtr[0], re.MULTILINE)
        ips = ips if len(ips) < 4 else ips[len(ips) -3:]
        for ip in list(ips): 
            if IPAddress(ip).is_private(): ips.remove(ip)
        if not ips: return "0.0.0.0",""
        results = Tools.fping(ips)
        latency = Tools.getAvrgAll(results)
        latency = dict(sorted(latency.items(), key=lambda item: item[1], reverse=True))
        for ip,ms in latency.items(): 
            if ms != 65000: return ip,ms
        return "0.0.0.0",""

    @staticmethod
    def fpingSource(server,ip,pings = 6):
        lastByte = re.findall("^([0-9.]+)\.([0-9]+)",server, re.MULTILINE | re.DOTALL)
        server = server if IPAddress(ip).version == 4 else server.replace("10.0.252.","fc10:252::")
        if server == "direct":
            results = Tools.fping([ip],6)
        else:
            results = Tools.fping([ip],6,f"fping -S {server} -c")
        return results,lastByte

    @staticmethod
    def fpingWorker(data):
        results,lastByte = Tools.fpingSource(data['server'],data['ip'])
        return {"results":results,"lastByte":lastByte,"ip":data['ip'],"server":data['server']}

    @staticmethod
    def getAvrgAll(results):
        latency = {}
        for ip,pings in results.items():
            avg = Tools.getAvrg(pings)
            latency[ip] = float(avg)
        latency = dict(sorted(latency.items(), key=lambda item: item[1]))
        return latency

    @staticmethod
    def getAvrg(row):
        result = 0
        if not row: return 65000
        for entry in row:
            #ignore timed out
            if entry[0] == "timed out": continue
            result += float(entry[0])
        #do not return 0, never, ever
        if result == 0: return 65000
        return int(float(result / len(row)))

    @staticmethod
    def checkASNGroup(files,asn):
        for asnsRaw,settings in files['config.json']['ASNGroups'].items():
            asns = asnsRaw.split(",")
            if str(asn) in asns:
                return {"asns":asnsRaw,"settings":settings}
                break
        return False

    @staticmethod
    def formatTable(list):
        longest,response = {},""
        for row in list:
            elements = row.split("\t")
            for index, entry in enumerate(elements):
                if not index in longest: longest[index] = 0
                if len(entry) > longest[index]: longest[index] = len(entry)
        for i, row in enumerate(list):
            elements = row.split("\t")
            for index, entry in enumerate(elements):
                if len(entry) < longest[index]:
                    diff = longest[index] - len(entry)
                    while len(entry) < longest[index]:
                        entry += " "
                response += f"{entry}" if response.endswith("\n") or response == "" else f" {entry}"
            if i < len(list) -1: response += "\n"
        return response
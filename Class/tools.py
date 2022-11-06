import subprocess, logging, re
from netaddr import IPAddress

class Tools:

    @staticmethod
    def cmd(cmd):
        p = subprocess.run(cmd, stdin=None, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
        return [p.stdout.decode('utf-8'),p.stderr.decode('utf-8')]
    
    @staticmethod
    def mtrIP(target,options,asndata):
        orgTarget = target
        if IPAddress(target).version == 4 and asndata[0] is not None and options["multi"] == True:
            logging.debug(f"ASN {asndata[0]} {target} multi")
            ips = [0,1,2,3,4,5,252,253,254]
            ip,prefix = options['subnet'].split("/")
            for entry in ips: target += f" {ip[:-1]}{entry}"
        fping = Tools.cmd(f"fping -c3 {target}")
        results = fping[1].split("\n")
        for result in results: 
            if "/0%" in result: return re.findall("^[a-z0-9.:]+",result, re.MULTILINE)[0],fping[0]
        logging.debug(f"{orgTarget} not reachable, trying to MTR")
        mtr = Tools.cmd('mtr '+orgTarget+' --report --report-cycles 3 --no-dns')
        ips = re.findall("-- ([0-9a-z.:]+)",mtr[0], re.MULTILINE)
        ips = ips if len(ips) < 4 else ips[len(ips) -3:]
        for ip in list(ips): 
            if IPAddress(ip).is_private(): ips.remove(ip)
        if not ips: 
            logging.debug(f"Could not find reachable IP for {orgTarget}")
            return "0.0.0.0",""
        fping = Tools.cmd(f"fping -c3 {' '.join(ips)}")
        results = fping[1].split("\n")
        for result in results: 
            if "/0%" in result: return re.findall("^[a-z0-9.:]+",result, re.MULTILINE)[0],fping[0]
        logging.debug(f"Could not find reachable IP for {orgTarget}")
        return "0.0.0.0",""

    @staticmethod
    def fpingSource(server,ip):
        lastByte = re.findall("^([0-9.]+)\.([0-9]+)",server, re.MULTILINE | re.DOTALL)
        server = server if IPAddress(ip).version == 4 else server.replace("10.0.252.","fc10:0:252::")
        if server == "direct":
            result = Tools.cmd("fping -c6 "+ip)[0]
        else:
            result = Tools.cmd("fping -c6 "+ip+" -S "+server)[0]
        parsed = re.findall("([a-z0-9:.]+).*?([0-9]+.[0-9]+|NaN avg).*?([0-9]+)% loss",result, re.MULTILINE)
        return parsed,result,lastByte

    @staticmethod
    def fpingWorker(data):
        parsed,result,lastByte = Tools.fpingSource(data['server'],data['ip'])
        return {"parsed":parsed,"result":result,"lastByte":lastByte,"ip":data['ip'],"server":data['server']}

    @staticmethod
    def getAvrg(fping):
        latency = []
        parsed = re.findall("([a-z0-9:.]+).*?([0-9]+.[0-9]+|NaN avg).*?([0-9]+)% loss",fping, re.MULTILINE)
        for ip,ms,loss in parsed:
            if ms == "NaN avg": continue
            latency.append(float(ms))
        if len(latency) > 1: del latency[0] #drop the first ping result
        if not latency: return 65000
        total = 0
        for ping in latency: total += ping
        return round(total / len(latency),2)

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
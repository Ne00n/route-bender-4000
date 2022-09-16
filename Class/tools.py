import subprocess, re

class Tools:

    @staticmethod
    def cmd(cmd):
        p = subprocess.run(cmd, stdin=None, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
        return [p.stdout.decode('utf-8'),p.stderr.decode('utf-8')]

    @staticmethod
    def isPrivate(ip):
        #Source https://stackoverflow.com/questions/691045/how-do-you-determine-if-an-ip-address-is-private-in-python
        priv_lo = re.compile("^127\.\d{1,3}\.\d{1,3}\.\d{1,3}$")
        priv_24 = re.compile("^10\.\d{1,3}\.\d{1,3}\.\d{1,3}$")
        priv_20 = re.compile("^192\.168\.\d{1,3}.\d{1,3}$")
        priv_16 = re.compile("^172.(1[6-9]|2[0-9]|3[0-1]).[0-9]{1,3}.[0-9]{1,3}$")
        return (priv_lo.match(ip) or priv_24.match(ip) or priv_20.match(ip) or priv_16.match(ip))
    
    @staticmethod
    def mtrIP(target,options,asndata):
        orgTarget = target
        if asndata[0] is not None and options["multi"] == True:
            ips = [1,2,3,252,253,254]
            ip,sub = asndata[1].split("/")
            target += " "+ip
            for entry in ips: target += f" {ip[:-1]}{entry}"
        direct = Tools.cmd("fping -c6 "+target)
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
            print(f"MTR running {target}")
            result = Tools.cmd('mtr '+target+' --report --report-cycles 4 --no-dns')
            parsed = re.findall("-- ([0-9.]+)",result[0], re.MULTILINE)
            for run in range(1,3):
                lastIP = parsed[len(parsed) - run]
                if Tools.isPrivate(lastIP):
                    print(lastIP+" is private, skipping")
                    return False,False
                if lastIP != "???":
                    direct = Tools.cmd("fping -c6 "+lastIP)
                if '100%' in direct[1]:
                    print(target,"("+lastIP+") not reachable.")
                else:
                    print(f"Found reachable IP in MTR {lastIP}")
                    return lastIP,direct
                if run == 2:
                    print("Could not find pingable IP for",target)
                    return False,False
        return target,direct

    @staticmethod
    def fpingSource(server,ip):
        lastByte = re.findall("^([0-9.]+)\.([0-9]+)",server, re.MULTILINE | re.DOTALL)
        if server == "direct":
            result = Tools.cmd("fping -c6 "+ip)[0]
        else:
            result = Tools.cmd("fping -c6 "+ip+" -S "+server)[0]
        parsed = re.findall("([0-9.]+).*?([0-9]+.[0-9]).*?([0-9])% loss",result, re.MULTILINE)
        return parsed,result,lastByte

    @staticmethod
    def fpingWorker(data):
        parsed,result,lastByte = Tools.fpingSource(data['server'],data['ip'])
        return {"parsed":parsed,"result":result,"lastByte":lastByte,"ip":data['ip'],"server":data['server']}

    @staticmethod
    def getAvrg(fping):
        latency = []
        parsed = re.findall("([0-9.]+).*?([0-9]+.[0-9]|NaN avg).*?([0-9]+)% loss",fping, re.MULTILINE)
        del parsed[0] #drop the first ping result
        for ip,ms,loss in parsed:
            if ms == "NaN avg": ms = 65000
            latency.append(float(ms))
        latency.sort()
        if len(latency) < 5: return 5000
        return round((float(latency[0]) + float(latency[1]) + float(latency[2])) / 3,2)

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
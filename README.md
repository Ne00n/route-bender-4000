Who needs BGP when you got Route Bender 4000<br />
JUST BEND YOUR WAY DoWN YOUr DESTINY

Addon for: https://github.com/Ne00n/pipe-builder-3000/ </br>

![data mining](https://i.pinimg.com/originals/ca/67/4d/ca674dde584640c77b55bcbd197575bb.gif)

**Why**<br />
Getting lower latency while gaming online

**Setup**<br />
[Wireguard](https://github.com/wireguard) as transport network + entry point<br />

**Features**<br >
- Automatic Latency optimization<br >
Just game seriously
- Cutting Edge Latency detection<br>
In case a IP does not like to ping, it will MTR it, plus some other stuff
- Cutting Edge rebending on idle connections<br >
If a connection is idle, it will be rebended after x hours to offer the lowest latency
- Rebending Protection on active connections<br >
If a connection cannot be optimized currently, it will be ignored until idle
- Packetloss bending protection<br >
Won't bend if Packetloss is detected over a specific route
- Pray & Disconnect if exit dies<br >
If any exit dies, all routes will be removed once detected

**Prepare**<br />
```
echo '333 BENDER' >> /etc/iproute2/rt_tables
cp config/pmacctd.conf /etc/pmacct/
cp config/nodes.example.json config/nodes.json
cp config/config.example.json config/config.json
ip6tables -t nat -A POSTROUTING -o vxlan1v6 -j MASQUERADE
iptables -t nat -A POSTROUTING -o vxlan1 -j MASQUERADE
ip6tables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
```
Configure config.json based on your needs + edit nodes.json

**Dependencies**<br />
```
apt-get install -y pmacct python3 python3-pip && pip3 install pyasn
```

**Usage**<br />
```
python3 bender.py
python3 bender.py deamon
python3 bender.py debug 1.1.1.1
python3 bender.py optimize 1.1.1.1 53
python3 bender.py level debug / info (default) / warning
python3 bender.py show
python3 bender.py clear
```
pmacct will execute bender.py every 60s, but you can still do it manually

**Reset everything**
```
systemctl stop pmacctd
rm data/history.json && rm data/loadBalancing.json
python3 bender.py clear
systemctl start pmacctd
```

**Update asn data**
```
pyasn_util_download.py --latestv46 && pyasn_util_convert.py --single rib.202* asn.dat
#or IPv4 only
pyasn_util_download.py --latestv4 && pyasn_util_convert.py --single rib.202* asn.dat
```

**Debugging**<br />
By default the logging runs on INFO and is getting saved to bender.log<br />
You can switch it to debug by supplying the parameter: bender.py level debug<br />

If you use functions such as optimize, debug, show, stats, clear... these are not logged, only printed, since they are intended for manual use.<br />

**Settings**<br />

ignore, if you wanna ignore an entire ASN, e.g Vivox<br />

By default, all ports will be monitored, to ignore ports, add them to ignorePorts<br />
If you want to skip that for specific ASN's then set ports = false e.g Fastly<br />

By default every subnet will be associated with the closest server. If loadBalancing is set to False,<br />
the first IP that does a connection to that ASN will determine the server for the entire ASN<br />

If the latency improvement is below 2ms or none, you can force bending by setting force to True<br />

You can define the size of the subnet that will be used to route dyn, /24 (default) or /32,<br />
dyn uses the actual subnet size from the routing table, this could result in issues when used for example with Microsoft or Google.</br >
Since they route the entire subnet, e.g /10 internally.

You can enable multi if the primary IP is not pingable it tries to figure out the gateway.<br />
This works for fine for some Networks like AWS but can cause problems with others like Google.<br />

Blacklist/Whitelist can be used to ignore/allow certain nodes for a specific ASN.<br />

lazy by default enabled, will not initially optimize active connections.<br />

**Config.json examples**
```
#Fastly CDN (Reddit...)
"54113" :{"ignore":false,"ports":false,"loadBalancing":true,"force":true,"route":"dyn"}
#Google (Youtube...)
"15169":{"ignore":false,"ports":true,"loadBalancing":true,"route":"/24"}
#Vivox (Voice communications, Valorant, Siege, Overwatch)
"393218":{"ignore":true,"ports":true,"loadBalancing":true,"route":"/24"}
```
You can also define ASN groups
```
"32163,55497,57976,40551":{"name":"blizzard","ignore":false,"ports":true,"loadBalancing":true,"route":"dyn"}
```

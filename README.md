Who needs BGP when you got Route Bender 4000<br />
JUST BEND YOUR WAY DoWN YOUr DESTINY

Addon for: https://github.com/Ne00n/pipe-builder-3000/ </br>

![data mining](https://i.pinimg.com/originals/ca/67/4d/ca674dde584640c77b55bcbd197575bb.gif)

**Why**<br />
Getting lower latency while gaming online

**Setup**<br />
[Wireguard](https://github.com/wireguard) as transport network + entry point<br />

**Prepare**<br />
```
echo '333 BENDER' >> /etc/iproute2/rt_tables
cp config/pmacctd.conf /etc/pmacct/
cp config/nodes.example.json config/nodes.json
cp config/config.example.json config/config.json
iptables -t nat -A POSTROUTING -o vxlan1 -j MASQUERADE
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
python3 bender.py clear
```
pmacct will execute bender.py every 60s, but you can still do it manually

**Update asn data**
```
pyasn_util_download.py --latest && pyasn_util_convert.py --single rib.2021* asn.dat
```

**Settings**
ignore, if you wanna ignore an entire ASN, e.g Vivox<br /><br />

By default, all ports will be monitored, to ignore ports, add them to ignorePorts<br />
If you want to skip that for specific ASN's then set ports = false e.g Fastly<br /><br />

By default every subnet will be associated with the closest server. If loadBalancing is set to False,<br />
the first IP that does a connection to that ASN will determine the server for the entire ASN<br /><br />

If the latency improvement is below 2ms or none, you can force bending by setting force to True<br /><br />

You can define the size of the subnet that will be used to route, <br /><br />
however I suggest just use dyn instead, which will use the actual size.<br />

**Config.json examples**
```
#Fastly CDN (Reddit...)
"54113" :{"ignore":false,"ports":false,"loadBalancing":true,"force":true,"route":"dyn"}
#Google (Youtube...)
"15169":{"ignore":false,"ports":true,"loadBalancing":true,"route":"dyn"}
#Vivox (Voice communications, Valorant, Siege, Overwatch)
393218":{"ignore":true,"ports":true,"loadBalancing":true,"route":"/24"}
```

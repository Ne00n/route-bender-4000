Who needs BGP when you got Route Bender 4000<br />
JUST BEND YOUR WAY DoWN YOUr DESTINY

![data mining](https://i.pinimg.com/originals/ca/67/4d/ca674dde584640c77b55bcbd197575bb.gif)

Addon for: https://github.com/Ne00n/pipe-builder-3000/ </br>

**Why**<br />
Getting lower latency while gaming online

**Setup**<br />
[Wireguard](https://github.com/wireguard) as transport network + entry point<br />

**Prepare**<br />
echo '333 BENDER' >> /etc/iproute2/rt_tables<br />
Rename hosts.example.json to hosts.json and fill it up<br />
```
iptables -t nat -A POSTROUTING -o vxlan1 -j MASQUERADE
iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
```

**Dependencies**<br />
```
apt-get install -y pmacct python3 python3-pip && pip3 install pyasn
```

**Usage**<br />
```
python3 bender.py
python3 bender.py clear
```

**Update asn data**
```
pyasn_util_download.py --latest && pyasn_util_convert.py --single rib.2021* asn.dat
```

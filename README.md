Who needs BGP when you got Route Bender 4000<br />
JUST BEND YOUR WAY DoWN YOUr DESTINY

**Why**<br />
Getting lower latency while gaming online

**Setup**<br />
[Wireguard](https://github.com/wireguard) as transport network + entry point<br />

**Prepare**<br />
echo '333 BENDER' >> /etc/iproute2/rt_tables<br />
rename nodes.example.json to nodes.json

**Dependencies**<br />
apt-get install -y pmacct python3

**Usage**<br />
python3 bender.py run

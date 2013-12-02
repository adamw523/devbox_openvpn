from fabric.api import prompt
from fabric.contrib.files import cd, exists, get, sed, upload_template
from fabric.operations import abort, run, sudo
from fabric.state import env

import ConfigParser
import fabtools
import re

config = ConfigParser.ConfigParser()
config.read(['private/openvpn.cfg'])

VALID_STATIC_OCTETS = [ [  1,  2], [  5,  6], [  9, 10], [ 13, 14], [ 17, 18],
                        [ 21, 22], [ 25, 26], [ 29, 30], [ 33, 34], [ 37, 38],
                        [ 41, 42], [ 45, 46], [ 49, 50], [ 53, 54], [ 57, 58],
                        [ 61, 62], [ 65, 66], [ 69, 70], [ 73, 74], [ 77, 78],
                        [ 81, 82], [ 85, 86], [ 89, 90], [ 93, 94], [ 97, 98],
                        [101,102], [105,106], [109,110], [113,114], [117,118],
                        [121,122], [125,126], [129,130], [133,134], [137,138],
                        [141,142], [145,146], [149,150], [153,154], [157,158],
                        [161,162], [165,166], [169,170], [173,174], [177,178],
                        [181,182], [185,186], [189,190], [193,194], [197,198],
                        [201,202], [205,206], [209,210], [213,214], [217,218],
                        [221,222], [225,226], [229,230], [233,234], [237,238],
                        [241,242], [245,246], [249,250], [253,254]]

def openvpn_install():
    """
    Install OpenVPN on server
    """
    fabtools.require.user('openvpn')

    fabtools.require.deb.packages(['openvpn', 'openvswitch-brcompat', 'ufw', 'libssl-dev', 'zip'])
    openvpn_vars = {
        "KEY_COUNTRY": config.get('openvpn', 'KEY_COUNTRY'),
        "KEY_PROVINCE": config.get('openvpn', 'KEY_PROVINCE'),
        "KEY_CITY": config.get('openvpn', 'KEY_CITY'),
        "KEY_ORG": config.get('openvpn', 'KEY_ORG'),
        "KEY_EMAIL": config.get('openvpn', 'KEY_EMAIL'),
        "KEY_CN": config.get('openvpn', 'KEY_CN'),
        "KEY_NAME": config.get('openvpn', 'KEY_NAME'),
        "KEY_OU": config.get('openvpn', 'KEY_OU'),
        "network": config.get('openvpn', 'network')
    }

    # install if easy-rsa hasn't been copied over and used yet
    if not exists('/home/openvpn/easy-rsa'):
        # use openvpns easy-rsa to create keys and configure openvpn
        sudo('mkdir ~openvpn/easy-rsa/', user='openvpn')

        # copy over easy-rsa tools from oepnvpn examples
        sudo('cp -r /usr/share/doc/openvpn/examples/easy-rsa/2.0/* ~openvpn/easy-rsa/', user='openvpn')
        sudo('chown -R openvpn:openvpn ~openvpn/easy-rsa')
        sed('~openvpn/easy-rsa/whichopensslcnf', 'openssl.cnf', 'openssl-1.0.0.cnf', use_sudo=True)

        # copy over server.conf file
        upload_template('devbox_openvpn/configs/openvpn_server.conf', '/etc/openvpn/server.conf', openvpn_vars, use_sudo=True)

        # coy over our variables
        upload_template('devbox_openvpn/configs/openvpn_vars.sh', '/home/openvpn/easy-rsa/vars', openvpn_vars, use_sudo=True)

        with cd('~openvpn/easy-rsa'):
            # create keys
            sudo('source ./vars; ./clean-all; ./build-dh; ./pkitool --initca; ./pkitool --server server', user='openvpn')

            with cd('keys'):
                # genreate the ta key and copy them into /etc/openvpn
                sudo('openvpn --genkey --secret ta.key', user='openvpn')
                sudo('cp server.crt server.key ca.crt dh1024.pem ta.key /etc/openvpn/')
                sudo('chmod 400 /etc/openvpn/ta.key')

        sudo('service openvpn start')

    # open up the firewall
    sudo('ufw allow 1194/udp')
    sudo('ufw allow 1194/tcp')
    sudo('ufw allow from %s/24' % (openvpn_vars['network']))

def openvpn_create_client():
    """
    Create client keys on server
    """
    hostname = prompt("Host name of the client:")

    # abort if client has been created already
    if exists('/home/openvpn/easy-rsa/keys/%s.crt' % (hostname), use_sudo=True):
        abort('Certificate for client already exists')

    # creeate client keys
    with cd('~openvpn/easy-rsa/'):
        sudo('source vars; ./build-key %s' % hostname, user='openvpn')

def openvpn_assign_static_ip():
    """
    Assign static IP address for a client
    """

    network = config.get('openvpn', 'network')
    network_pref = re.sub(r'(.*\.)(.+)\b', r'\1', network)
    network_prompt = network_pref + 'x'

    hostname = prompt("Host name of the client:")

    print "Valid IP endings:",
    print ",".join([str(v[0]) for v in VALID_STATIC_OCTETS])
    octet = prompt("Choose an ending octet from the above list (%s) :" % (network_prompt))

    if not exists('/etc/openvpn/ccd'):
        sudo('mkdir /etc/openvpn/ccd')

    template_vars = {'network_pref': network_pref, 'oct1': octet, 'oct2': str(int(octet) + 1)}
    upload_template('devbox_openvpn/configs/ccd_template', '/etc/openvpn/ccd/%s' % (hostname), template_vars, use_sudo=True)

def openvpn_download_visc():
    """
    Download OpenVPN configuration files for Viscosity
    """
    hostname = prompt("Host name of the client:")

    if not exists('/home/openvpn/easy-rsa/keys/%s.crt' % (hostname), use_sudo=True):
        abort('Create client keys first with: openvpn_create_client')

    # set up a new directory to create our .visc configruation
    tmp_dir = '/tmp/%s' % (hostname + '.visc')
    if exists(tmp_dir):
        sudo('rm -fR %s' % (tmp_dir))

    # vars for the configuration file
    client_conf = {
        "visc_name": hostname,
        "server": env.hosts[0]
    }

    # make tmp directory, copy required items into it
    sudo('mkdir %s' % (tmp_dir))
    sudo('cp /etc/openvpn/ca.crt %s/ca.crt' % (tmp_dir))
    sudo('cp ~openvpn/easy-rsa/keys/%s.crt %s/cert.crt' % (hostname, tmp_dir))
    sudo('cp ~openvpn/easy-rsa/keys/%s.key %s/key.key' % (hostname, tmp_dir))
    sudo('cp /etc/openvpn/ta.key %s/ta.key' % (tmp_dir))
    upload_template('devbox_openvpn/configs/client.visc/config.conf', '%s/config.conf' % (tmp_dir), client_conf, use_sudo=True)
    sudo('chmod -R a+r %s' % (tmp_dir))

    # download .vsic directory and then delete it from server
    get(tmp_dir, '.')
    sudo('rm -fR %s' % (tmp_dir))

def openvpn_download_ovpn():
    """
    Download OpenVPN configuration files for OpenVPN
    """
    hostname = prompt("Host name of the client:")

    if not exists('/home/openvpn/easy-rsa/keys/%s.crt' % (hostname), use_sudo=True):
        abort('Create client keys first with: openvpn_create_client')

    # set up a new directory to create our .visc configruation
    tmp_dir = '/tmp/%s' % (hostname + '')
    if exists(tmp_dir):
        sudo('rm -fR %s' % (tmp_dir))

    # vars for the configuration file
    client_conf = {
        "visc_name": hostname,
        "server": env.hosts[0]
    }

    # make tmp directory, copy required items into it
    sudo('mkdir %s' % (tmp_dir))
    sudo('cp /etc/openvpn/ca.crt %s/ca.crt' % (tmp_dir))
    sudo('cp ~openvpn/easy-rsa/keys/%s.crt %s/cert.crt' % (hostname, tmp_dir))
    sudo('cp ~openvpn/easy-rsa/keys/%s.key %s/key.key' % (hostname, tmp_dir))
    sudo('cp /etc/openvpn/ta.key %s/ta.key' % (tmp_dir))
    upload_template('devbox_openvpn/configs/client.ovpn', '%s/config.ovpn' % (tmp_dir), client_conf, use_sudo=True)
    sudo('chmod -R a+r %s' % (tmp_dir))

    # zip up the directory
    with cd('/tmp/'):
        sudo('zip -r %s.zip %s' % (hostname, hostname))

    # download .vsic directory and then delete it from server
    get('/tmp/%s.zip' % (hostname))
    sudo('rm -fR %s' % (tmp_dir))
    sudo('rm /tmp/%s.zip' % (hostname))


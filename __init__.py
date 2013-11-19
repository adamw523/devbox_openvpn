from fabric.api import prompt
from fabric.contrib.files import cd, exists, get, upload_template
from fabric.operations import sudo
from fabric.state import env

import ConfigParser

config = ConfigParser.ConfigParser()
config.read(['private/openvpn.cfg'])

def openvpn_install():
    """
    Install OpenVPN on server
    """
    require.user('openvpn')

    fabtools.require.deb.packages(['openvpn', 'openvswitch-brcompat'])
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

        # copy over server.conf file
        upload_template('openvpn/configs/openvpn_server.conf', '/etc/openvpn/server.conf', openvpn_vars, use_sudo=True)

        # coy over our variables
        upload_template('openvpn/configs/openvpn_vars.sh', '/home/openvpn/easy-rsa/vars', openvpn_vars, use_sudo=True)

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
    # sudo('cp /etc/openvpn/server.crt %s/server.crt' % (tmp_dir))
    sudo('cp ~openvpn/easy-rsa/keys/%s.crt %s/cert.crt' % (hostname, tmp_dir))
    sudo('cp ~openvpn/easy-rsa/keys/%s.key %s/key.key' % (hostname, tmp_dir))
    sudo('cp /etc/openvpn/ta.key %s/ta.key' % (tmp_dir))
    upload_template('openvpn/configs/client.visc/config.conf', '%s/config.conf' % (tmp_dir), client_conf, use_sudo=True)
    sudo('chmod -R a+r %s' % (tmp_dir))

    # download .vsic directory and then delete it from server
    get(tmp_dir, '.')
    sudo('rm -fR %s' % (tmp_dir))
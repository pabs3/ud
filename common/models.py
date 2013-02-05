# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 675 Mass Ave, Cambridge, MA 02139, USA.
#
# Copyright (C) 2013 Luca Filipozzi <lfilipoz@debian.org>

from django.core.validators import validate_email
from django.core.exceptions import ValidationError

from ldapdb.models.fields import CharField, IntegerField, ListField
import ldapdb.models
import ldap
ldap.set_option(ldap.OPT_X_TLS_CACERTFILE, '/etc/ssl/certs/ca-certificates.crt')

from pyparsing import CaselessKeyword, LineEnd, LineStart, Literal, ParseException, QuotedString
from pyparsing import delimitedList

import base64
import datetime
import hashlib
import struct
import time
import re
from IPy import IP
from M2Crypto import RSA, m2

# not IDN ready
def validate_dns_labels(val):
    disallowed = re.compile('[^A-Z\d-]', re.IGNORECASE)
    for label in val.split('.'):
        if len(label) == 0:
            raise ValidationError('label in name is too short')
        if len(label) > 63:
            raise ValidationError('label in name is too long')
        if label.startswith('-') or label.endswith('-'):
            raise ValidationError('label in name begins/ends with hyphen')
        if disallowed.search(label):
            raise ValidationError('label in name contains invalid characters')

# fully qualified domain name
def validate_fqdn(val):
    if len(val) > 255:
        raise ValidationError('name is too long')
    if not val.endswith('.'):
        raise ValidationError('name does not end in .')
    validate_dns_labels(val[:-1])
    
# partially qualified domain name
def validate_pqdn(val):
    if len(val) > (255 - len('.debian.net.')):
        raise ValidationError('label is too long')
    if val.endswith('.'):
        raise ValidationError('label ends in .')
    if val.endswith('.debian.net'):
        raise ValidationError('label ends in .debian.net')
    validate_dns_labels(val)

def validate_ipv4(val):
    address = IP(val)
    if address.version() != 4:
        raise ValidationError('value is not an IPv4 address')

def validate_ipv6(val):
    address = IP(val)
    if address.version() != 6:
        raise ValidationError('value is not an IPv6 address')

def validate_bATVToken(val):
    return # TODO

def validate_birthDate(val):
    return # TODO

def validate_c(val):
    if len(val) < 2:
        raise ValidationError('value is too short')
    if len(val) > 2:
        raise ValidationError('value is too long')

def validate_dnsZoneEntry(val):
    return # TODO ... but ListField

def validate_emailForward(val):
    try:
        validate_email(val)
    except:
        raise ValidationError('value is not a valid email address')

def validate_facsimileTelephoneNumber(val):
    return # TODO

def validate_ircNick(val):
    return # TODO

def validate_l(val):
    return # TODO

def validate_loginShell(val):
    return # TODO

def validate_sshRSAAuthKey(val):
    return # TODO ... but ListField

def validate_sshRSAAuthKey_key(encoded_key):
    decoded_key = base64.b64decode(encoded_key)
    if base64.b64encode(decoded_key).rstrip() != encoded_key:
        raise ParseException('key has incorrect base64 encoding')

    # OpenSSH public keys of type 'ssh-rsa' have three parts, where each
    # part is encoded in OpenSSL MPINT format (4-byte big-endian bit-count
    # followed by the appropriate number of bits).

    try: # part 1: key type hardcoded value ('ssh-rsa')
        x = struct.unpack('>I', decoded_key[:4])[0]
        key_type, decoded_key = decoded_key[4:x+4], decoded_key[x+4:]
    except:
        raise ParseException('unable to extract type from key')
    if key_type != 'ssh-rsa':
        raise ParseException('key is not an ssh-rsa key')

    try: # part 2: public exponent
        x = struct.unpack('>I', decoded_key[:4])[0]
        e, decoded_key = decoded_key[:x+4], decoded_key[x+4:]
    except:
        raise ParseException('unable to extract public exponent from key')

    try: # part 3: large prime
        x = struct.unpack('>I', decoded_key[:4])[0]
        n, decoded_key = decoded_key[:x+4], decoded_key[x+4:]
    except:
        raise ParseException('unable to extract large prime from key')

    try: # creating a new RSA key
        created_key = RSA.new_pub_key((e, n))
    except:
        raise ParseException('unable to create key using values extracted from provided key')

    if encoded_key != base64.b64encode('\0\0\0\7ssh-rsa%s%s' % created_key.pub()):
        raise ParseException('newly created key and provided key do not match')

    key_size = len(created_key)
    if key_size not in [1024, 2048, 4096]:
        raise ParseException('key must have size 1024, 2048 or 4096 bits')

    fingerprint = hashlib.md5(encoded_key).hexdigest()[12:]
    for line in file('/usr/share/ssh/blacklist.RSA-%d' % (key_size)):
        if fingerprint == line.rstrip():
            raise ParseException('key is weak (debian openssl fiasco)')

def validate_sshRSAAuthKey_options(options):
    flag = (
        # reject flags: cert-authority
        CaselessKeyword('no-agent-forwarding') |
        CaselessKeyword('no-port-forwarding') |
        CaselessKeyword('no-pty') |
        CaselessKeyword('no-user-rc') |
        CaselessKeyword('no-X11-forwarding')
    )
    key = (
        # reject keys: principals, tunnel
        CaselessKeyword('command') |
        CaselessKeyword('environment') |
        CaselessKeyword('from') |
        CaselessKeyword('permitopen')
    )
    keyval = key + Literal('=') + QuotedString('"', unquoteResults=False)
    valid_options = LineStart() + delimitedList(flag | keyval, combine=True) + LineEnd()
    try:
        valid_options.parseString(options)
    except:
        raise ParseException('options are not valid')

def validate_sshRSAAuthKey_allowed_hosts(allowed_hosts):
    if not set(allowed_hosts).issubset(set([x.hostname for x in Host.objects.all()])):
        raise ParseException('unknown host in allowed_hosts')


class Host(ldapdb.models.Model):
    base_dn = 'ou=hosts,dc=debian,dc=org'
    object_classes = ['debianServer']
    allowedGroups               = ListField(    db_column='allowedGroups',            editable = False)
    hid                         = CharField(    db_column='host',                     editable = False, primary_key=True)
    hostname                    = CharField(    db_column='hostname',                 editable = False)

    def __str__(self):
        return self.hid

    def __unicode__(self):
        return self.hid


class Group(ldapdb.models.Model):
    base_dn = 'ou=users,dc=debian,dc=org'
    object_classes = ['debianGroup']
    gid                         = CharField(    db_column='gid',                      editable = False, primary_key=True)
    gidNumber                   = CharField(    db_column='gidNumber',                editable = False)
    subGroup                    = ListField(    db_column='subGroup',                 editable = False)

    def __str__(self):
        return self.gid

    def __unicode__(self):
        return self.gid


class User(ldapdb.models.Model):
    base_dn = 'ou=users,dc=debian,dc=org'
    object_classes = ['debianAccount']
    accountStatus               = CharField(    db_column='accountStatus',            editable = False)
    allowedHost                 = ListField(    db_column='allowedHost',              editable = False)
    bATVToken                   = CharField(    db_column='bATVToken',                validators=[validate_bATVToken])
    birthDate                   = CharField(    db_column='birthDate',                validators=[validate_birthDate])
    c                           = CharField(    db_column='c',                        validators=[validate_c])
    cn                          = CharField(    db_column='cn',                       editable = False)
    dnsZoneEntry                = ListField(    db_column='dnsZoneEntry',             validators=[validate_dnsZoneEntry])
    emailForward                = CharField(    db_column='emailForward',             validators=[validate_emailForward])
    facsimileTelephoneNumber    = CharField(    db_column='facsimileTelephoneNumber', validators=[validate_facsimileTelephoneNumber])
    gecos                       = CharField(    db_column='gecos',                    editable = False)
    gidNumber                   = CharField(    db_column='gidNumber',                editable = False)
    # TODO gender
    # TODO icqUin
    ircNick                     = CharField(    db_column='ircNick',                  validators=[validate_ircNick])
    # TODO jabberJID
    # TODO jpegPhoto
    keyFingerPrint              = CharField(    db_column='keyFingerPrint',           editable = False)
    l                           = CharField(    db_column='l',                        validators=[validate_l])
    # TODO labeledURI
    # TODO latitude
    loginShell                  = CharField(    db_column='loginShell',               validators=[validate_loginShell])
    # TODO longitude
    # TODO mailCallout
    # TODO mailContentInspectionAction
    # TODO mailDefaultOptions
    # TODO mailDisableMessage
    # TODO mailGreylisting
    # TODO mailRBL
    # TODO mailRHSBL
    # TODO mailWhitelist
    # TODO onVacation
    # TODO postalAddress
    # TODO postalCode
    shadowExpire                = CharField(    db_column='shadowExpire',             editable = False)
    shadowInactive              = CharField(    db_column='shadowInactive',           editable = False)
    shadowLastChange            = CharField(    db_column='shadowLastChange',         editable = False)
    shadowMax                   = CharField(    db_column='shadowMax',                editable = False)
    shadowMin                   = CharField(    db_column='shadowMin',                editable = False)
    shadowWarning               = CharField(    db_column='shadowWarning',            editable = False)
    sn                          = CharField(    db_column='sn',                       editable = False)
    sshRSAAuthKey               = ListField(    db_column='sshRSAAuthKey',            validators=[validate_sshRSAAuthKey])
    supplementaryGid            = ListField(    db_column='supplementaryGid',         editable = False)
    # TODO telephoneNumber
    # TODO VoIP
    uid                         = CharField(    db_column='uid',                      editable = False, primary_key=True)
    uidNumber                   = CharField(    db_column='uidNumber',                editable = False)
    userPassword                = CharField(    db_column='userPassword',             editable = False)

    def __str__(self):
        return self.uid

    def __unicode__(self):
        return self.uid

    def update(self, key, val):
        (field, model, direct, m2m) = self._meta.get_field_by_name(key)
        print type(field)
        if direct and not m2m:
            setattr(self, key, field.clean(val, self))

    def __delete_dnsZoneEntry(self, query, delete_all=False):
        users = User.objects.filter(dnsZoneEntry__startswith=query)
        if len(users) == 1: # one user owns the resource record
            if users[0].uid == self.uid: # if that user is me
                records = [x for x in self.dnsZoneEntry if x.startswith(query)]
                if delete_all:
                    for old_value in records:
                        self.dnsZoneEntry.remove(old_value)
                else:
                    if len(records) == 1:
                        old_value = records[0]
                        self.dnsZoneEntry.remove(old_value)
                    else:
                        raise ValidationError('record cannot be deleted: multiple records')
            else:
                raise ValidationError('record cannot be deleted: owned by another user')
        if len(users) >= 2: # two or more users own the record ... should never happen
            raise ValidationError('record cannot be deleted: owned by multiple users')

    def __update_dnsZoneEntry(self, query, new_value, allow_multiple=False):
        users = User.objects.filter(dnsZoneEntry__startswith=query)
        if len(users) == 0: # no user owns the resource record
            self.dnsZoneEntry.append(new_value)
        if len(users) == 1: # one user owns the resource record
            if users[0].uid == self.uid: # if that user is me
                records = [x for x in self.dnsZoneEntry if x.startswith(query)]
                if allow_multiple:
                    if new_value not in records:
                        self.dnsZoneEntry.append(new_value)
                else:
                    if len(records) == 1:
                        old_value = records[0]
                        if new_value != old_value: # change if different
                            self.dnsZoneEntry.remove(old_value)
                            self.dnsZoneEntry.append(new_value)
                    else:
                        raise ValidationError('record cannot be added: multiple entries')
            else:
                raise ValidationError('record cannot be added: owned by another user')
        if len(users) >= 2: # two or more users own the record ... should never happen
            raise ValidationError('record cannot be added: owned by multiple users')

    def delete_dnsZoneEntry(self, name):
        validate_pqdn(name)
        query = '%s' % (name.lower())
        self.__delete_dnsZoneEntry(query, True)

    def delete_dnsZoneEntry_IN_A(self, name):
        validate_pqdn(name)
        query = '%s IN A' % (name.lower())
        self.__delete_dnsZoneEntry(query)

    def update_dnsZoneEntry_IN_A(self, name, address):
        validate_pqdn(name)
        validate_ipv4(address)
        query = '%s IN A' % (name.lower())
        value = '%s IN A %s' % (name.lower(), address)
        self.__update_dnsZoneEntry(query, value)

    def delete_dnsZoneEntry_IN_AAAA(self, name):
        validate_pqdn(name)
        query = '%s IN AAAA' % (name.lower())
        self.__delete_dnsZoneEntry(query)

    def update_dnsZoneEntry_IN_AAAA(self, name, address):
        validate_pqdn(name)
        validate_ipv6(address)
        query = '%s IN AAAA' % (name.lower())
        value = '%s IN AAAA %s' % (name.lower(), address)
        self.__update_dnsZoneEntry(query, value)

    def delete_dnsZoneEntry_IN_CNAME(self, name):
        validate_pqdn(name)
        query = '%s IN CNAME' % (name.lower())
        self.__delete_dnsZoneEntry(query)

    def update_dnsZoneEntry_IN_CNAME(self, name, cname):
        validate_pqdn(name)
        validate_fqdn(cname)
        query = '%s IN CNAME' % (name.lower())
        value = '%s IN CNAME %s' % (name.lower(), cname.lower())
        self.__update_dnsZoneEntry(query, value)

    def delete_dnsZoneEntry_IN_MX(self, name):
        validate_pqdn(name)
        query = '%s IN MX' % (name.lower())
        self.__delete_dnsZoneEntry(query, True)

    def update_dnsZoneEntry_IN_MX(self, name, preference, exchange):
        validate_pqdn(name)
        if int(preference) < 1 or int(preference) > 999:
            raise ValidationError('preference %s out of range' % preference)
        validate_fqdn(exchange)
        query = '%s IN MX' % (name.lower())
        value = '%s IN MX %d %s' % (name.lower(), int(preference), exchange.lower())
        self.__update_dnsZoneEntry(query, value, True)

    def delete_dnsZoneEntry_IN_TXT(self, name):
        validate_pqdn(name)
        query = '%s IN TXT' % (name.lower())
        self.__delete_dnsZoneEntry(query)

    def update_dnsZoneEntry_IN_TXT(self, name, txtdata):
        validate_pqdn(name)
        # TODO validate txtdata
        query = '%s IN TXT' % (name.lower())
        value = '%s IN TXT %s' % (name.lower(), txtdata)
        self.__update_dnsZoneEntry(query, value)

    def __delete_ListField(self, key, query):
        field = getattr(self, key)
        records = [x for x in field if query in x]
        for record in records:
            field.remove(record)

    # a given key can only be used once
    def __update_ListField(self, key, query, new_value):
        field = getattr(self, key)
        records = [x for x in field if query in x]
        if len(records) == 0:
            field.append(new_value)
        if len(records) == 1:
            old_value = records[0]
            if new_value != old_value: # change if different
                field.remove(old_value)
                field.append(new_value)
        if len(records) >= 2: # should not get here
            raise ValidationError('field cannot be updated: multiple entries exist!')

    def delete_sshRSAAuthKey(self, key):
        validate_sshRSAAuthKey_key(key)
        query = key
        self.__delete_ListField('sshRSAAuthKey', query)

    def update_sshRSAAuthKey(self, key, allowed_hosts=[], options=None, comment=None):
        value = ''
        if allowed_hosts:
            validate_sshRSAAuthKey_allowed_hosts(allowed_hosts)
            value = 'allowed_hosts=%s ' % (','.join(allowed_hosts))
        if options:
            validate_sshRSAAuthKey_options(options)
            value += '%s ' % (options)
        validate_sshRSAAuthKey_key(key)
        query = key
        value += 'ssh-rsa %s' % (key)
        if comment:
            # TODO validate comment
            value += ' %s' % (comment)
        self.__update_ListField('sshRSAAuthKey', query, value)

    def is_retired(self):
        if self.accountStatus:
            parts = self.accountStatus.split()
            status = parts[0]
            if status == 'inactive':
                return True
            elif status == 'memorial':
                return True
            elif status == 'retiring':
                # We'll give them a few extra days over what we said
                age = 6 * 31 * 24 * 60 * 60
                try:
                    return (time.time() - time.mktime(time.strptime(parts[1], '%Y-%m-%d'))) > age
                except IndexError:
                    return False
                except ValueError:
                    return False
        return False

    def is_not_retired(self):
        return not self.is_retired()

    def has_active_password(self):
        if not self.userPassword:
            return False
        if self.userPassword.upper() == '{CRYPT}*LK*':
            return False
        if self.userPassword.upper().startswith("{CRYPT}!"):
            return False
        return True

    def has_locked_password(self):
        return self.has_active_password()

    def is_allowed_by_hostacl(self, desired_hostname):
        if not self.allowedHost:
            return False
        if desired_hostname in self.allowedHost:
            return True
        for entry in self.allowedHost:
            parts = entry.split(None, 1)
            if len(parts) == 1:
                continue
            (allowed_hostname, expire) = parts
            if allowed_hostname != desired_hostname:
                continue
            try:
                parsed = datetime.datetime.strptime(expire, '%Y%m%d')
            except ValueError:
                return False
            return parsed >= datetime.datetime.now()
        return False

    def _get_password(self):
        p = self.userPassword
        if not p.upper().startswith('{CRYPT}') or len(p) > 50:
            return p
        else:
            return p[7:]
    password = property(_get_password)

    def _get_expire(self):
        if not self.has_active_password():
            return '1' # not 0; see Debian Bug #308229
        else:
            return self.shadowExpire
    expire = property(_get_expire)
    

# vim: ts=4 sw=4 et ai si sta:

import argparse
from bz2 import BZ2Decompressor
from datetime import datetime
from email import policy
from email.parser import BytesParser
from email.message import EmailMessage
from geolite2 import geolite2
from grafana_client import GrafanaApi
from grafana_client.util import setup_logging
from grafanalib._gen import DashboardEncoder
from grafanalib.core import Dashboard
import gzip
import json
import logging
import lzma
import mysql.connector
import os
import pandas as pd
import re
import socket
import tldextract
import xml.etree.ElementTree as ET
import zipfile

parser = argparse.ArgumentParser(description="DMARC Analyser",
                                 formatter_class=argparse.ArgumentDefaultsHelpFormatter)

parser.add_argument("-i", "--init", action="store_true", help="create brand new MySQL database")
parser.add_argument("-s", "--show", action="store_true", help="show the database and Grafana response")

args = parser.parse_args()
config = vars(args)

with open('root.txt', 'r') as file:
    user, pwd = file.read().split('\n')

path_rua = "altair.ac6.fr/rua/"
path_ruf = "altair.ac6.fr/ruf/"
path_mail_rua = "dmarc-reports/rua/mail/"
path_mail_ruf = "dmarc-reports/ruf/mail/"
path_attachment_rua = "dmarc-reports/rua/attachment/"
path_attachment_ruf = "dmarc-reports/ruf/attachment/"
path_report_rua = "dmarc-reports/rua/report/"
path_report_ruf = "dmarc-reports/ruf/report/"

decompressor = BZ2Decompressor()
reader = geolite2.reader()
logger = logging.getLogger(__name__)
setup_logging(level=logging.DEBUG)
grafana_client = GrafanaApi.from_url()

template_rua_meta = {
    "org_name":'./report_metadata/org_name',
    "org_email":'./report_metadata/email',
    "org_extra_contact_info":'./report_metadata/extra_contact_info',
    "report_id":'./report_metadata/report_id',
    "begin_date":'./report_metadata/date_range/begin',
    "end_date":'./report_metadata/date_range/end',
    "domain":'./policy_published/domain',
    "adkim":'./policy_published/adkim',
    "aspf":'./policy_published/aspf',
    "p":'./policy_published/p',
    "sp":'./policy_published/sp',
    "pct":'./policy_published/pct',
    "fo":'./policy_published/fo'
}

template_rua_record = {
    "source_ip_address":'row/source_ip',
    "source_country":'',
    'lat':'',
    'lon':'',
    "source_reverse_dns":'',
    "source_base_domain":'',
    "count":'row/count',
    "spf_aligned":'row/policy_evaluated/spf',
    "dkim_aligned":'row/policy_evaluated/dkim',
    "dmarc_aligned":'',
    "disposition":'row/policy_evaluated/disposition',
    "policy_override_reasons":'row/policy_evaluated/reason',
    "policy_override_comments":'row/policy_evaluated/reason/comment',
    "envelope_from":'identifiers/envelope_from',
    "header_from":'identifiers/header_from',
    "envelope_to":'identifiers/envelope_to',
    "dkim_domain":'auth_results/dkim/domain',
    "dkim_selector":'auth_results/dkim/selector',
    "dkim_result":'auth_results/dkim/result',
    "spf_domain":'auth_results/spf/domain',
    "spf_scope":'auth_results/spf/scope',
    "spf_result":'auth_results/spf/result',
    'time':'',
    'dkim_pass':'',
    'dkim_fail':'',
    'spf_pass':'',
    'spf_fail':'',
    'dispo_none':'',
    'dispo_quarantine':'',
    'dispo_reject':'',
    'dkim_unaligned':'',
    'spf_unaligned':'',
    'dmarc_unaligned':'',
    'dkim_aligned_w':'',
    'spf_aligned_w':'',
    'dmarc_aligned_w':'',
}

template_ruf = {
    'feedback_type':'Feedback-Type: (.*)\n',
    'user_agent':'User-Agent: (.*)\n',
    'version':'Version: (.*)\n',
    'original_from':'Original-Mail-From: (.*)\n',
    'original_to':'Original-Rcpt-To: (.*)\n',
    'arrival_date':'Arrival-Date: (.*)\n',
    'id':'Message-ID: (.*)\n',
    'auth_results':'Authentication-Results: (.*)\n',
    'source_ip':'Source-IP: (.*)\n',
    'source_country':'',
    'lat':'',
    'lon':'',
    'delivery_result':'Delivery-Result: (.*)\n',
    'auth_failure':'Auth-Failure: (.*)\n',
    'reported_domain':'Reported-Domain: (.*)\n',
    'original_envelope_id':'Original-Envelope-Id: (.*)\n',
    'dkim_domain':'DKIM-Domain: (.*)\n',
    'identity_alignment':'Identity-Alignment: (.*)\n'
}

iso_codes = {
    'AF':'33.0,65.0', 'AL':'41.0,20.0', 'DZ':'28.0,3.0', 'AS':'-14.3333,-170.0', 'AD':'42.5,1.6', 'AO':'-12.5,18.5', 'AI':'18.25,-63.1667', 'AQ':'-90.0,0.0', 'AG':'17.05,-61.8', 'AR':'-34.0,-64.0', 'AM':'40.0,45.0', 'AW':'12.5,-69.9667', 'AU':'-27.0,133.0', 'AT':'47.3333,13.3333', 'AZ':'40.5,47.5', 'BS':'24.25,-76.0', 'BH':'26.0,50.55', 'BD':'24.0,90.0', 'BB':'13.1667,-59.5333', 'BY':'53.0,28.0', 'BE':'50.8333,4.0', 'BZ':'17.25,-88.75', 'BJ':'9.5,2.25', 'BM':'32.3333,-64.75', 'BT':'27.5,90.5', 'BO':'-17.0,-65.0', 'BA':'44.0,18.0', 'BW':'-22.0,24.0', 'BV':'-54.4333,3.4', 'BR':'-10.0,-55.0', 'IO':'-6.0,71.5', 'BN':'4.5,114.6667', 'BG':'43.0,25.0', 'BF':'13.0,-2.0', 'BI':'-3.5,30.0', 'KH':'13.0,105.0', 'CM':'6.0,12.0', 'CA':'60.0,-95.0', 'CV':'16.0,-24.0', 'KY':'19.5,-80.5', 'CF':'7.0,21.0', 'TD':'15.0,19.0', 'CL':'-30.0,-71.0', 'CN':'35.0,105.0', 'CX':'-10.5,105.6667', 'CC':'-12.5,96.8333', 'CO':'4.0,-72.0', 'KM':'-12.1667,44.25', 'CG':'-1.0,15.0', 'CD':'0.0,25.0', 'CK':'-21.2333,-159.7667', 'CR':'10.0,-84.0', 'CI':'8.0,-5.0', 'HR':'45.1667,15.5', 'CU':'21.5,-80.0', 'CY':'35.0,33.0', 'CZ':'49.75,15.5', 'DK':'56.0,10.0', 'DJ':'11.5,43.0', 'DM':'15.4167,-61.3333', 'DO':'19.0,-70.6667', 'EC':'-2.0,-77.5', 'EG':'27.0,30.0', 'SV':'13.8333,-88.9167', 'GQ':'2.0,10.0', 'ER':'15.0,39.0', 'EE':'59.0,26.0', 'ET':'8.0,38.0', 'FK':'-51.75,-59.0', 'FO':'62.0,-7.0', 'FJ':'-18.0,175.0', 'FI':'64.0,26.0', 'FR':'46.0,2.0', 'GF':'4.0,-53.0', 'PF':'-15.0,-140.0', 'TF':'-43.0,67.0', 'GA':'-1.0,11.75', 'GM':'13.4667,-16.5667', 'GE':'42.0,43.5', 'DE':'51.0,9.0', 'GH':'8.0,-2.0', 'GI':'36.1833,-5.3667', 'GR':'39.0,22.0', 'GL':'72.0,-40.0', 'GD':'12.1167,-61.6667', 'GP':'16.25,-61.5833', 'GU':'13.4667,144.7833', 'GT':'15.5,-90.25', 'GG':'49.5,-2.56', 'GN':'11.0,-10.0', 'GW':'12.0,-15.0', 'GY':'5.0,-59.0', 'HT':'19.0,-72.4167', 'HM':'-53.1,72.5167', 'VA':'41.9,12.45', 'HN':'15.0,-86.5', 'HK':'22.25,114.1667', 'HU':'47.0,20.0', 'IS':'65.0,-18.0', 'IN':'20.0,77.0', 'ID':'-5.0,120.0', 'IR':'32.0,53.0', 'IQ':'33.0,44.0', 'IE':'53.0,-8.0', 'IM':'54.23,-4.55', 'IL':'31.5,34.75', 'IT':'42.8333,12.8333', 'JM':'18.25,-77.5', 'JP':'36.0,138.0', 'JE':'49.21,-2.13', 'JO':'31.0,36.0', 'KZ':'48.0,68.0', 'KE':'1.0,38.0', 'KI':'1.4167,173.0', 'KP':'40.0,127.0', 'KR':'37.0,127.5', 'KW':'29.3375,47.6581', 'KG':'41.0,75.0', 'LA':'18.0,105.0', 'LV':'57.0,25.0', 'LB':'33.8333,35.8333', 'LS':'-29.5,28.5', 'LR':'6.5,-9.5', 'LY':'25.0,17.0', 'LI':'47.1667,9.5333', 'LT':'56.0,24.0', 'LU':'49.75,6.1667', 'MO':'22.1667,113.55', 'MK':'41.8333,22.0', 'MG':'-20.0,47.0', 'MW':'-13.5,34.0', 'MY':'2.5,112.5', 'MV':'3.25,73.0', 'ML':'17.0,-4.0', 'MT':'35.8333,14.5833', 'MH':'9.0,168.0', 'MQ':'14.6667,-61.0', 'MR':'20.0,-12.0', 'MU':'-20.2833,57.55', 'YT':'-12.8333,45.1667', 'MX':'23.0,-102.0', 'FM':'6.9167,158.25', 'MD':'47.0,29.0', 'MC':'43.7333,7.4', 'MN':'46.0,105.0', 'ME':'42.0,19.0', 'MS':'16.75,-62.2', 'MA':'32.0,-5.0', 'MZ':'-18.25,35.0', 'MM':'22.0,98.0', 'NA':'-22.0,17.0', 'NR':'-0.5333,166.9167', 'NP':'28.0,84.0', 'NL':'52.5,5.75', 'AN':'12.25,-68.75', 'NC':'-21.5,165.5', 'NZ':'-41.0,174.0', 'NI':'13.0,-85.0', 'NE':'16.0,8.0', 'NG':'10.0,8.0', 'NU':'-19.0333,-169.8667', 'NF':'-29.0333,167.95', 'MP':'15.2,145.75', 'NO':'62.0,10.0', 'OM':'21.0,57.0', 'PK':'30.0,70.0', 'PW':'7.5,134.5', 'PS':'32.0,35.25', 'PA':'9.0,-80.0', 'PG':'-6.0,147.0', 'PY':'-23.0,-58.0', 'PE':'-10.0,-76.0', 'PH':'13.0,122.0', 'PN':'-24.7,-127.4', 'PL':'52.0,20.0', 'PT':'39.5,-8.0', 'PR':'18.25,-66.5', 'QA':'25.5,51.25', 'RE':'-21.1,55.6', 'RO':'46.0,25.0', 'RU':'60.0,100.0', 'RW':'-2.0,30.0', 'SH':'-15.9333,-5.7', 'KN':'17.3333,-62.75', 'LC':'13.8833,-61.1333', 'PM':'46.8333,-56.3333', 'VC':'13.25,-61.2', 'WS':'-13.5833,-172.3333', 'SM':'43.7667,12.4167', 'ST':'1.0,7.0', 'SA':'25.0,45.0', 'SN':'14.0,-14.0', 'RS':'44.0,21.0', 'SC':'-4.5833,55.6667', 'SL':'8.5,-11.5', 'SG':'1.3667,103.8', 'SK':'48.6667,19.5', 'SI':'46.0,15.0', 'SB':'-8.0,159.0', 'SO':'10.0,49.0', 'ZA':'-29.0,24.0', 'GS':'-54.5,-37.0', 'SS':'8.0,30.0', 'ES':'40.0,-4.0', 'LK':'7.0,81.0', 'SD':'15.0,30.0', 'SR':'4.0,-56.0', 'SJ':'78.0,20.0', 'SZ':'-26.5,31.5', 'SE':'62.0,15.0', 'CH':'47.0,8.0', 'SY':'35.0,38.0', 'TW':'23.5,121.0', 'TJ':'39.0,71.0', 'TZ':'-6.0,35.0', 'TH':'15.0,100.0', 'TL':'-8.55,125.5167', 'TG':'8.0,1.1667', 'TK':'-9.0,-172.0', 'TO':'-20.0,-175.0', 'TT':'11.0,-61.0', 'TN':'34.0,9.0', 'TR':'39.0,35.0', 'TM':'40.0,60.0', 'TC':'21.75,-71.5833', 'TV':'-8.0,178.0', 'UG':'1.0,32.0', 'UA':'49.0,32.0', 'AE':'24.0,54.0', 'GB':'54.0,-2.0', 'US':'38.0,-97.0', 'UM':'19.2833,166.6', 'UY':'-33.0,-56.0', 'UZ':'41.0,64.0', 'VU':'-16.0,167.0', 'VE':'8.0,-66.0', 'VN':'16.0,106.0', 'VG':'18.5,-64.5', 'VI':'18.3333,-64.8333', 'WF':'-13.3,-176.2', 'EH':'24.5,-13.0', 'YE':'15.0,48.0', 'ZM':'-15.0,30.0', 'ZW':'-20.0,30.0'
}

initialize_rua = """
    CREATE TABLE RUA (
    record_id INTEGER,
    org_name VARCHAR(255),
    org_email VARCHAR(255),
    org_extra_contact_info VARCHAR(255),
    report_id VARCHAR(255),
    begin_date VARCHAR(255),
    end_date VARCHAR(255),
    domain VARCHAR(255),
    adkim VARCHAR(255),
    aspf VARCHAR(255),
    p VARCHAR(255),
    sp VARCHAR(255),
    pct INTEGER,
    fo INTEGER,
    source_ip_address VARCHAR(255),
    source_country VARCHAR(255),
    lat VARCHAR(255),
    lon VARCHAR(255),
    source_reverse_dns VARCHAR(255),
    source_base_domain VARCHAR(255),
    count INTEGER,
    spf_aligned INTEGER,
    dkim_aligned INTEGER,
    dmarc_aligned INTEGER,
    disposition VARCHAR(255),
    policy_override_reasons VARCHAR(255),
    policy_override_comments VARCHAR(255),
    envelope_from VARCHAR(255),
    header_from VARCHAR(255),
    envelope_to VARCHAR(255),
    dkim_domain VARCHAR(255),
    dkim_selector VARCHAR(255),
    dkim_result VARCHAR(255),
    spf_domain VARCHAR(255),
    spf_scope VARCHAR(255),
    spf_result VARCHAR(255),
    time DATE,
    dkim_pass INTEGER,
    dkim_fail INTEGER,
    spf_pass INTEGER,
    spf_fail INTEGER,
    dispo_none INTEGER,
    dispo_quarantine INTEGER,
    dispo_reject INTEGER,
    dkim_unaligned INTEGER,
    spf_unaligned INTEGER,
    dmarc_unaligned INTEGER,
    dkim_aligned_w INTEGER,
    spf_aligned_w INTEGER,
    dmarc_aligned_w INTEGER,
    PRIMARY KEY (record_id))
    """

insert_rua = """
    INSERT INTO RUA (record_id, org_name, org_email, org_extra_contact_info, report_id, begin_date, end_date,
    domain, adkim, aspf, p, sp, pct, fo, source_ip_address, source_country, lat, lon, source_reverse_dns, source_base_domain,
    count, spf_aligned, dkim_aligned, dmarc_aligned, disposition, policy_override_reasons, policy_override_comments,
    envelope_from, header_from, envelope_to, dkim_domain, dkim_selector, dkim_result, spf_domain, spf_scope,
    spf_result, time, dkim_pass, dkim_fail, spf_pass, spf_fail, dispo_none, dispo_quarantine, dispo_reject, dkim_unaligned,
    spf_unaligned, dmarc_unaligned, dkim_aligned_w, spf_aligned_w, dmarc_aligned_w) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """

initialize_ruf = """
    CREATE TABLE RUF (
    record_id INTEGER,
    feedback_type VARCHAR(255),
    user_agent VARCHAR(255),
    version VARCHAR(255),
    original_from VARCHAR(255),
    original_to VARCHAR(255),
    arrival_date VARCHAR(255),
    id VARCHAR(255),
    auth_results VARCHAR(255),
    source_ip VARCHAR(255),
    source_country VARCHAR(255),
    lat VARCHAR(255),
    lon VARCHAR(255),
    delivery_result VARCHAR(255),
    auth_failure VARCHAR(255),
    reported_domain VARCHAR(255),
    original_envelope_id VARCHAR(255),
    dkim_domain VARCHAR(255),
    identity_alignment VARCHAR(255),
    PRIMARY KEY (record_id))
    """

insert_ruf = """
    INSERT INTO RUF (record_id, feedback_type, user_agent, version, original_from, original_to, arrival_date, id, auth_results, source_ip, source_country, lat, lon,
    delivery_result, auth_failure, reported_domain, original_envelope_id, dkim_domain,
    identity_alignment) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """


def unzip(email, path_in, path_out, overwrite = False, full_path = False):
    unzip = False
    if not full_path:
        file_path = path_in + email
        output_path = path_out + email
    else:
        file_path = email
        output_path = path_out + email.rsplit('/', 1)[1]

    if email.endswith('.bz2'):
        output_path = output_path.replace('.bz2', '')
        with open(file_path, 'rb') as file, open(output_path, 'wb') as new_file:
            for data in iter(lambda : file.read(100 * 1024), b''):
                new_file.write(decompressor.decompress(data))
                unzip = True

    if email.endswith('.gz'):
        output_path = output_path.replace('.gz', '')
        with gzip.open(file_path) as f, open(output_path, 'wb') as fout:
            file_content = f.read()
            fout.write(file_content)
            unzip = True

    if email.endswith('.xz'):
        output_path = output_path.replace('.xz', '')
        with lzma.open(file_path) as f, open(output_path, 'wb') as fout:
            file_content = f.read()
            fout.write(file_content)
            unzip = True
    
    if email.endswith('.zip'):
        with zipfile.ZipFile(file_path, 'r') as fzip:
            fzip.extractall(path_out)
            unzip = True

    if not unzip:
        with open(file_path, 'rb') as f, open(output_path, 'wb') as fout:
            file_content = f.read()
            fout.write(file_content)

    if overwrite and not email.endswith('.mail'):
        os.remove(file_path)


def get_attachment(email, path_mail, path_report, path_attachment):
    if email.endswith('.xml'):
        with open(path_mail + email, 'rb') as fin, open(path_report + email, 'wb') as fout:
            data = fin.read()
            fout.write(data)
        
        os.remove(path_mail + email)
        return

    elif email.endswith('.eml'):
        with open(path_mail + email, 'rb') as fin, open(path_report + email, 'wb') as fout:
            data = fin.read()
            fout.write(data)

        return

    mail = BytesParser(policy=policy.default).parse(open(path_mail + email, 'rb'))

    for attachment in mail.iter_attachments():
        name = attachment.get_filename()
        if name == None:
            name = email + '.report'
        data = attachment.get_content()

        if type(data) == EmailMessage:
            data = data.as_bytes()
            name = name + '.message'
        
        with open(path_attachment + name, 'wb') as f:
            f.write(data)


def gather_rua(path_emails, path_mail, path_report, path_attachment):
    for email in path_emails:
        unzip(email, path_rua, path_mail, full_path=True)
    
    emails = os.listdir(path_mail)
    
    for email in emails:
        get_attachment(email, path_mail, path_report, path_attachment)
    
    reports = os.listdir(path_attachment)
    
    for report in reports:
        unzip(report, path_attachment, path_report)
    
    reports = os.listdir(path_report)
    reports_data = []
    
    for report in reports:
        tree = ET.parse(path_report + report)
        root = tree.getroot()
        rua_meta = template_rua_meta.copy()
    
        for key, value in template_rua_meta.items():
            if key == 'begin_date' or key == 'end_date':
                date = root.find(value).text
                info = datetime.utcfromtimestamp(float(date))
                info = info.strftime('%Y-%m-%d %H:%M:%S')
                rua_meta[key] = info
                continue
    
            try:
                info = root.find(value)
                rua_meta[key] = info.text
            except AttributeError:
                if key == 'fo':
                    rua_meta[key] = '0'
                    continue
    
                rua_meta[key] = ''
                continue
        
        report_number = len(root.findall('record'))
    
        for report_n in range(report_number):
            rua_record = template_rua_record.copy()
    
            for key, value in template_rua_record.items():
                value = './record[' + str(report_n+1) + ']/' + value
    
                try:
                    info = root.find(value)
                    rua_record[key] = info.text
                except AttributeError:
                    rua_record[key] = ''
                    continue
            
            ip_address = root.find('./record/row/source_ip').text
            try:
                country = reader.get(ip_address)['country']['iso_code']
            except TypeError:
                country = ''
            try:
                domain = socket.gethostbyaddr(ip_address)[0]
                base_domain = tldextract.extract(domain).registered_domain
            except socket.herror:
                domain = ''
                base_domain = ''
            rua_record['source_country'] = country
            try:
                rua_record['lat'], rua_record['lon'] = iso_codes[country].split(',')
            except:
                rua_record['lat'], rua_record['lon'] = '', ''
            rua_record['source_reverse_dns'] = domain
            rua_record['source_base_domain'] = base_domain
            if rua_record['spf_aligned'] == 'pass':
                rua_record['spf_aligned'] = True
            else:
                rua_record['spf_aligned'] = False
            if rua_record['dkim_aligned'] == 'pass':
                rua_record['dkim_aligned'] = True
            else:
                rua_record['dkim_aligned'] = False
            rua_record['dmarc_aligned'] = rua_record['spf_aligned'] or rua_record['dkim_aligned']
            if rua_record['dkim_selector'] == '':
                rua_record['dkim_selector'] = 'none'
            if rua_record['dkim_result'] == '':
                rua_record['dkim_result'] = 'none'
            if rua_record['spf_scope'] == '':
                rua_record['spf_scope'] = 'mfrom'
            if rua_record['spf_result'] == '':
                rua_record['spf_result'] = 'none'
            
            rua_record['time'] = rua_meta['begin_date'][0:10]
            if rua_record['dkim_result'] == 'pass':
                rua_record['dkim_pass'] = 1 * int(float(rua_record['count']))
            else:
                rua_record['dkim_pass'] = 0
            if rua_record['dkim_result'] == 'fail':
                rua_record['dkim_fail'] = 1 * int(float(rua_record['count']))
            else:
                rua_record['dkim_fail'] = 0
            if rua_record['spf_result'] == 'pass':
                rua_record['spf_pass'] = 1 * int(float(rua_record['count']))
            else:
                rua_record['spf_pass'] = 0
            if rua_record['spf_result'] == 'fail':
                rua_record['spf_fail'] = 1 * int(float(rua_record['count']))
            else:
                rua_record['spf_fail'] = 0
            if rua_record['disposition'] == 'none':
                rua_record['dispo_none'] = 1 * int(float(rua_record['count']))
            else:
                rua_record['dispo_none'] = 0
            if rua_record['disposition'] == 'quarantine':
                rua_record['dispo_quarantine'] = 1 * int(float(rua_record['count']))
            else:
                rua_record['dispo_quarantine'] = 0
            if rua_record['disposition'] == 'reject':
                rua_record['dispo_reject'] = 1 * int(float(rua_record['count']))
            else:
                rua_record['dispo_reject'] = 0
            if rua_record['dkim_aligned'] == 0:
                rua_record['dkim_unaligned'] = 1 * int(float(rua_record['count']))
            else:
                rua_record['dkim_unaligned'] = 0
            if rua_record['spf_aligned'] == 0:
                rua_record['spf_unaligned'] = 1 * int(float(rua_record['count']))
            else:
                rua_record['spf_unaligned'] = 0
            if rua_record['dmarc_aligned'] == 0:
                rua_record['dmarc_unaligned'] = 1 * int(float(rua_record['count']))
            else:
                rua_record['dmarc_unaligned'] = 0
            rua_record['dkim_aligned_w'] = int(float(rua_record['dkim_aligned'])) * int(float(rua_record['count']))
            rua_record['spf_aligned_w'] = int(float(rua_record['spf_aligned'])) * int(float(rua_record['count']))
            rua_record['dmarc_aligned_w'] = int(float(rua_record['dmarc_aligned'])) * int(float(rua_record['count']))

            reports_data.append(rua_meta | rua_record)
    
    return reports_data


def gather_ruf(path_emails, path_mail, path_report, path_attachment):
    for email in path_emails:
        unzip(email, path_ruf, path_mail, full_path=True)
    
    emails = os.listdir(path_mail)
    
    for email in emails:
        get_attachment(email, path_mail, path_report, path_attachment)
    
    reports = os.listdir(path_attachment)
    
    for report in reports:
        unzip(report, path_attachment, path_report)
    
    reports = os.listdir(path_report)
    reports_data = []

    for report in reports:
        if not report.endswith('.message') and not report.endswith('.eml'):
            with open(path_report + report, 'r') as f:
                content = f.read()
        
            parsed_report = template_ruf.copy()

            for key, value in template_ruf.items():
                try:
                    parsed_report[key] = re.search(value, content).group(1)
                except (AttributeError, IndexError) as error:
                    parsed_report[key] = ''

            ip_address = parsed_report['source_ip']
            try:
                country = reader.get(ip_address)['country']['iso_code']
            except (TypeError, ValueError) as error:
                country = ''
            parsed_report['source_country'] = country
            try:
                parsed_report['lat'], parsed_report['lon'] = iso_codes[country].split(',')
            except:
                parsed_report['lat'], parsed_report['lon'] = '', ''
    
            reports_data.append(parsed_report)
    
    return reports_data


def init_dashboard():
    dashboard = Dashboard(uid='SDksirRWz', title='DMARC Reports')
    data = {
        "dashboard": json.loads(json.dumps(dashboard, sort_keys=True, cls=DashboardEncoder)),
        "overwrite": True,
        "message": '',
    }
    GrafanaApi.from_env()
    grafana_client.dashboard.update_dashboard(data)


def update_dashboard(show = False):
    with open('report.json', 'r', encoding='utf-8') as f:
        template = json.loads(f.read())
    
    dashboard = {
        "dashboard": template,
        "overwrite": True,
        "message": "Updated via Script",
        "uid": "SDksirRWz",
    }
    
    response = grafana_client.dashboard.update_dashboard(dashboard)

    if show:
        print(json.dumps(response, indent=2))


def initialization(show = False):
    mydb = mysql.connector.connect(host="localhost", user=user, password=pwd)
    mycursor = mydb.cursor(buffered=True)
    mycursor.execute('CREATE DATABASE DMARC')
    mydb.close()

    mydb = mysql.connector.connect(host="localhost", user=user, password=pwd, database='DMARC')
    mycursor = mydb.cursor(buffered=True)

    mycursor.execute(initialize_rua)
    mydb.commit()

    mycursor.execute(initialize_ruf)
    mydb.commit()

    path_emails, last_file = [], ''
    for path, subdirs, files in os.walk(path_rua):
        for name in files:
            path_emails.append(os.path.join(path, name).replace("\\","/"))
    
    path_emails.sort(key=lambda x: os.path.getmtime(x))
    last_file = path_emails[-1]
    last_rua = [last_file, os.stat(last_file).st_size]
    last_file = None

    reports_data = gather_rua(path_emails, path_mail_rua, path_report_rua, path_attachment_rua)
    mycursor.execute('SELECT MAX(record_id) FROM DMARC.RUA')
    max_id = mycursor.fetchone()[0]
    if max_id == None:
        max_id = 0

    data, id = [], max_id + 1
    for report in reports_data:
        entry = list(report.values())
        entry.insert(0, id)
        id += 1
        data.append(tuple(entry))

    mycursor.executemany(insert_rua, data)
    mydb.commit()
    
    path_emails = []
    for path, subdirs, files in os.walk(path_ruf):
        for name in files:
            path_emails.append(os.path.join(path, name).replace("\\","/"))
    
    path_emails.sort(key=lambda x: os.path.getmtime(x))

    try:
        last_file = path_emails[-1]
    except IndexError:
        last_file = None

    if not last_file == None:
        last_ruf = [last_file, os.stat(last_file).st_size]
    else:
        last_ruf = ['None', 'None']
    
    if path_emails != []:
        reports_data = gather_ruf(path_emails, path_mail_ruf, path_report_ruf, path_attachment_ruf)
        mycursor.execute('SELECT MAX(record_id) FROM DMARC.RUF')
        max_id = mycursor.fetchone()[0]
        if max_id == None:
            max_id = 0
    
        data, id = [], max_id + 1
        for report in reports_data:
            entry = list(report.values())
            entry.insert(0, id)
            id += 1
            data.append(tuple(entry))
    
        mycursor.executemany(insert_ruf, data)
        mydb.commit()
        mydb.close()

    with open('last.txt', 'w') as f:
        f.write('Last RUA name: ' + last_rua[0] + '\nLast RUA size: ' + str(last_rua[1]) + '\nLast RUF name: ' + last_ruf[0] + '\nLast RUF size: ' + str(last_ruf[1]))

    path_cleanup = []
    for path, subdirs, files in os.walk('dmarc-reports'):
        for name in files:
            path_cleanup.append(os.path.join(path, name).replace("\\","/"))
    
    path_cleanup = filter(os.path.isfile, path_cleanup)
    for file in path_cleanup:
        os.remove(file)

    init_dashboard()
    update_dashboard(show)


def execution(show = False):
    mydb = mysql.connector.connect(host="localhost", user=user, password=pwd, database='DMARC')
    mycursor = mydb.cursor(buffered=True)

    path_emails = []
    for path, subdirs, files in os.walk(path_rua):
        for name in files:
            path_emails.append(os.path.join(path, name).replace("\\","/"))

    path_emails.sort(key=lambda x: os.path.getmtime(x))
    last_file = path_emails[-1]

    with open('last.txt', 'r') as f:
        content = f.read()
        try:
            last_rua = re.search('Last RUA name: (.*)\n', content).group(1)
            last_rua_size = re.search('Last RUA size: (.*)\n', content).group(1)
        except (AttributeError, IndexError) as error:
            last_rua = ''

    if last_rua in path_emails:
        path_emails_new = path_emails[path_emails.index(last_rua):]
        if str(os.stat(last_rua).st_size) == last_rua_size:
            path_emails_new.pop(0)
    else:
        path_emails_new = path_emails

    last_rua = [last_file, os.stat(last_file).st_size]
    last_file = None

    if path_emails_new != []:
        reports_data = gather_rua(path_emails_new, path_mail_rua, path_report_rua, path_attachment_rua)
        mycursor.execute('SELECT MAX(record_id) FROM DMARC.RUA')
        max_id = mycursor.fetchone()[0]
        if max_id == None:
            max_id = 0
    
        data, id = [], max_id + 1
        for report in reports_data:
            entry = list(report.values())
            entry.insert(0, id)
            id += 1
            data.append(tuple(entry))
    
        mycursor.executemany(insert_rua, data)
        mydb.commit()

    path_emails = []
    for path, subdirs, files in os.walk(path_ruf):
        for name in files:
            path_emails.append(os.path.join(path, name).replace("\\","/"))

    path_emails.sort(key=lambda x: os.path.getmtime(x))
    try:
        last_file = path_emails[-1]
    except IndexError:
        last_file = None

    with open('last.txt', 'r') as f:
        content = f.read()
        try:
            last_ruf = re.search('Last RUF name: (.*)\n', content).group(1)
            last_ruf_size = re.search('Last RUF size: (.*)\n', content).group(1)
        except (AttributeError, IndexError) as error:
            last_ruf = ''

    if last_ruf in path_emails:
        path_emails_new = path_emails[path_emails.index(last_ruf):]
        if str(os.stat(last_ruf).st_size) == last_ruf_size:
            path_emails.pop(0)
    else:
        path_emails_new = path_emails

    if not last_file == None:
        last_ruf = [last_file, os.stat(last_file).st_size]
    else:
        last_ruf = ['None', 'None']

    if path_emails_new != []:
        reports_data = gather_ruf(path_emails_new, path_mail_ruf, path_report_ruf, path_attachment_ruf)
        mycursor.execute('SELECT MAX(record_id) FROM DMARC.RUF')
        max_id = mycursor.fetchone()[0]
        if max_id == None:
            max_id = 0
    
        data, id = [], max_id + 1
        for report in reports_data:
            entry = list(report.values())
            entry.insert(0, id)
            id += 1
            data.append(tuple(entry))
    
        mycursor.executemany(insert_ruf, data)
        mydb.commit()

    if show:
        database = pd.read_sql('SELECT * FROM DMARC.RUA', mydb)
        print(database)
        database = pd.read_sql('SELECT * FROM DMARC.RUF', mydb)
        print(database)
    
    mydb.close()

    with open('last.txt', 'w') as f:
        f.write('Last RUA name: ' + last_rua[0] + '\nLast RUA size: ' + str(last_rua[1]) + '\nLast RUF name: ' + last_ruf[0] + '\nLast RUF size: ' + str(last_ruf[1]))

    path_cleanup = []
    for path, subdirs, files in os.walk('dmarc-reports'):
        for name in files:
            path_cleanup.append(os.path.join(path, name).replace("\\","/"))
    
    path_cleanup = filter(os.path.isfile, path_cleanup)
    for file in path_cleanup:
        os.remove(file)

    update_dashboard(show)



if config['init']:
    initialization(config['show'])
else:
    execution(config['show'])
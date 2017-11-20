#!/usr/bin/env python
"""Parse Data Exporterator"""
from __future__ import division

import base64
import datetime
import logging
import re
import time

from google.appengine.api import app_identity
from google.appengine.api import urlfetch
from google.cloud import storage
import googleapiclient.discovery             # noqa: I201

from flask import Flask                      # noqa: I100
import requests                              # noqa: I201
import requests_toolbelt.adapters.appengine  # noqa: I201
import yaml                                  # noqa: I201


API_URL         = 'https://...'              # noqa: E221
API_PATH        = '/parse'                   # noqa: E221
KMS_BUCKET      = '...'                      # noqa: E221
KMS_LOCATION    = '...'                      # noqa: E221
KMS_KEYRING     = '...'                      # noqa: E221
DATA_BUCKET     = '...'                      # noqa: E221
PARSE_CRYPTOKEY = '...'                      # noqa: E221
PARSE_API_FILE  = '...'                      # noqa: E221
CLASSES         = ('...,'                    # noqa: E221, E501
                   '...,'                    # noqa: E221, E501
                   '...')                    # noqa: E221, E501
REQUEST_SKIP    = 0                          # noqa: E221
REQUEST_LIMIT   = 100                        # noqa: E221


app = Flask(__name__)
requests_toolbelt.adapters.appengine.monkeypatch()
urlfetch.set_default_fetch_deadline(45)


def _decrypt(project_id, location, keyring, cryptokey, cipher_text):
    """Decrypts and returns string from given cipher text."""
    logging.info('Decrypting cryptokey: {}'.format(cryptokey))
    kms_client = googleapiclient.discovery.build('cloudkms', 'v1')
    name = 'projects/{}/locations/{}/keyRings/{}/cryptoKeys/{}'.format(
        project_id, location, keyring, cryptokey)
    cryptokeys = kms_client.projects().locations().keyRings().cryptoKeys()
    request = cryptokeys.decrypt(
        name=name,
        body={'ciphertext': base64.b64encode(cipher_text).decode('ascii')})
    response = request.execute()
    return base64.b64decode(response['plaintext'].encode('ascii'))


def _download_output(output_bucket, filename):
    """Downloads the output file from GCS and returns it as a string."""
    logging.info('Downloading output file')
    client = storage.Client()
    bucket = client.get_bucket(output_bucket)
    output_blob = (
        'keys/{}'
        .format(filename))
    return bucket.blob(output_blob).download_as_string()


def get_credentials(cryptokey, filename):
    """Fetches credentials from KMS returning a decrypted API key."""
    credentials_enc = _download_output(KMS_BUCKET, filename)
    credentials_dec = _decrypt(app_identity.get_application_id(),
                               KMS_LOCATION,
                               KMS_KEYRING,
                               cryptokey,
                               credentials_enc)
    credentials_dec_yaml = yaml.load(credentials_dec)
    return credentials_dec_yaml


def request_parse(endpoint, parse_creds, skip):
    """Makes individual requests to Parse."""
    header_dict = {'X-Parse-Application-Id': parse_creds['app_id'],
                   'X-Parse-REST-API-Key': parse_creds['rest_key'],
                   'X-Parse-Master-Key': parse_creds['master_key'],
                   }

    params_dict = {'limit': REQUEST_LIMIT,
                   'skip': skip,
                   }

    url = API_URL + API_PATH + endpoint

    try:
        r = requests.get(url, params=params_dict, headers=header_dict)
        response = r.json()
    except Exception as error:
        logging.error('An error occurred requesting data from parse: {0}'.format(error))  # noqa: E501
        response = None
        raise error

    return response


def fetch_parse(parse_creds):
    """Fetches data from Parse."""
    logging.info('Fetching data from Parse')

    class_list = CLASSES.split(',')
    DEFAULT_CLASSES = {'User': 'users',
                       'Installation': 'installations'}

    results = {}
    for classname in class_list:
        results[classname] = []
        object_count = 0
        skip_count = 0

        if classname not in DEFAULT_CLASSES.keys():
            endpoint = '/{0}/{1}'.format('classes', classname)
        else:
            endpoint = '/{0}'.format(DEFAULT_CLASSES[classname])

        logging.info('Fetching {0} table data - '.format(classname))

        while True:
            start_timer = time.clock()
            skip = skip_count * REQUEST_LIMIT

            response = request_parse(endpoint, parse_creds, skip)

            if 'results' in response.keys() and len(response['results']) > 1:
                object_count += len(response['results'])
                skip_count = skip_count + 1
                results[classname].extend(response['results'])
            else:
                time_passed = time.clock() - start_timer
                logging.info('Got: {0} records in {1} secs'.format(object_count, time_passed))  # noqa: E501
                break

    return results


def make_csv(json):
    """Takes input data (JSON) and return text in CSV-like format."""
    logging.info('Making CSV string from data')

    csv_dict = {}
    for classname, rows in json.iteritems():
        for row in rows:
            if classname not in csv_dict:
                headers = ', '.join(row.keys())
                csv_dict[classname] = '{0}\n'.format(headers)

            formatted_row = []
            for value_row in row.values():
                # TODO: This is absolute garbage and should be fixed at some point.                            # noqa: E501
                # This is being done because JSON > CSV directly would be utterly annoying and                 # noqa: E501
                # fairly useless.  This could be done much cleaner if an actual parser was written.            # noqa: E501
                try:
                    if type(value_row) is dict:
                        formatted_row.append('"{0}"'.format(', '.join([', '.join(                              # noqa: E501
                            [key, str(val)]) for key, val in value_row.items()])))                             # noqa: E501
                    elif (type(value_row) is bool) or (type(value_row) is float) or (type(value_row) is int):  # noqa: E501
                        formatted_row.append('"{0}"'.format(str(value_row)))
                    elif type(value_row) is list:
                        # We know these lists to contain dicts, Oy!
                        flattened_row = []
                        for elem in value_row:
                            if type(elem) is dict:
                                flattened_row.append('"{0}"'.format(', '.join([', '.join(                      # noqa: E501
                                    [key, str(val)]) for key, val in elem.items()])))                          # noqa: E501
                            else:
                                logging.error('Did not expect a list to contain '                              # noqa: E501
                                    'non-dictionaries, Data: {0}'.format(value_row))                           # noqa: E501
                        formatted_row.append('"{0}"'.format(', '.join(flattened_row)))                         # noqa: E501
                    elif type(value_row) is unicode:
                        encoded_row = value_row.encode('ascii', 'ignore').decode('ascii')                      # noqa: E501
                        formatted_row.append('"{0}"'.format(encoded_row))
                    else:
                        logging.error('Unknown data type: {0} for value: {1}'.format(                          # noqa: E501
                            type(value_row), value_row))
                except TypeError as error:
                    logging.error('An error occurred parsing JSON to CSV: '
                                  '{0}, Row: {1}'.format(error, value_row))
                    raise

            formatted_str = ', '.join(formatted_row)

            # Sanitizer, very basic for now.
            # TODO: Make smarter and more configurable.
            formatted_str = re.sub(r'"[^"]+token[^"]+"', '"[REDACTED]"', formatted_str, flags=re.IGNORECASE)   # noqa: E501

            csv_dict[classname] += '{0}\n'.format(formatted_str)

    return csv_dict


def write_data_to_gcs(csv):
    """Writes CSV to GCS."""
    logging.info('Uploading data to GCS')
    client = storage.Client()
    bucket = client.get_bucket(DATA_BUCKET)
    now_iso8601 = datetime.datetime.utcnow().isoformat('T')

    for classname, results in csv.iteritems():
        filename_to_create = '{0}/{1}.csv'.format(now_iso8601, classname)
        try:
            blob = storage.Blob(filename_to_create, bucket)
            blob.upload_from_string(results)
        except Exception as error:
            logging.error('An error occurred uploading data to GCS: {0}'.format(error))  # noqa: E501
            raise error


def runit():
    """Runs the task."""
    parse_creds = get_credentials(PARSE_CRYPTOKEY, PARSE_API_FILE)

    json = fetch_parse(parse_creds)
    csv  = make_csv(json)  # noqa: E221
    write_data_to_gcs(csv)


@app.route('/run')
def run():
    runit()
    return 'Completed', 200


@app.errorhandler(500)
def server_error(e):
    # Log the error and stacktrace.
    logging.exception('An error occurred during a request.')
    return 'An internal error occurred.', 500

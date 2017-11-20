# Parse Exporterator

Export data from Parse to Google Cloud Storage (GCS).

Currently CSV is supported but other export formats could be added if desired.

## Overview Diagram

![overview diagram](https://github.com/drewrothstein/parse-exporterator/raw/master/errata/exporterator.png)

## Screenshots

### Cron Schedule

![cron schedule](https://github.com/drewrothstein/parse-exporterator/raw/master/errata/cron_schedule.png)

### GCS Bucket

![bucket ui](https://github.com/drewrothstein/parse-exporterator/raw/master/errata/gcs_ui.png)

### GCS Bucket Files

![bucket files](https://github.com/drewrothstein/parse-exporterator/raw/master/errata/gcs_files.png)

## What does it do?

It exports data from Parse to a CSV that is stored on GCS at the specified run interval.

## Where does this run?

This is built to run on the Google App Engine Standard Environment as a Scheduled Task.

## How does it work?

It queries a hosted Parse API ([doc](http://docs.parseplatform.org/rest/guide/)), and stores the data in Google Cloud Storage ([doc](https://cloud.google.com/storage/)).

## Dependencies

See the `requirements.txt` for the list of Python package dependencies.

This relies on successful responses from a Parse API and Google Cloud Storage APIs.

This is built to operate on Google App Engine and thus has dependencies on all of the relevant underlying infrastructure on Google Cloud Platform.

Google Cloud Platform Service Dependencies:
1) App Engine (Standard Environment)
2) Cloud Storage
3) Key Management Service

## Prerequisites

### Accounts

1. Google Cloud Platform Account.
2. Parse API Credentials.

### System

1. Python 2.7.
2. Working `pip` installation.
3. Installation of `gcloud` SDK and the `dev_appserver.py` loaded into your `PATH` ([doc](https://cloud.google.com/sdk/)).

## Configuration

### Cron Schedule

See `cron.yaml`.

### Secure Key Storage

To securely store the Parse API Credentials for access by the service from Google App Engine I have chosen to use Google's Key Management Service. Two initial one-time steps need to be completed for this to work.

1) Encrypt and upload the secrets to Google's Key Management Service.
2) Grant the appropriate Service Account access to decrypt the secrets.

Fetch your Parse API Credentials to be able to proceed.

1) Encrypt Secrets

We will create a Service Account in Google IAM to be able to encrypt / decrypt our secrets (which you could create separate encrypt/decrypt accounts and permissions if you would like).

To create a Service Account:
```
$ gcloud --project PROJECT_ID iam service-accounts create SERVICE_ACCOUNT_NAME
$ gcloud --project PROJECT_ID iam service-accounts keys create key.json \
--iam-account SERVICE_ACCOUNT_NAME@PROJECT_ID.iam.gserviceaccount.com
```

This creates a Service Account and a JSON file with the credentials which we can use to encrypt / decrypt our secrets outside of KMS.

One of the easiest ways to interact with Google KMS is to start with the samples from the GCP Samples [Here](https://github.com/GoogleCloudPlatform/python-docs-samples).

A quick note about compatibility. If you already have this repository cloned, a [change](https://github.com/GoogleCloudPlatform/python-docs-samples/commit/e0f957c816a42117a02c3d6db09e0611c15d4c70) was pushed that updates how blobs are encoded/decoded. It is not backwards compatible with previous code and will error your application at runtime with something like the SO post mentioned in the commit. This code is updated to support *only* the new encoding/decoding but if you have trouble because you previously cloned this reposity, `git pull`, re-encrypt and you should be good to go.

Once you have this repository cloned, you will create a keyring and cryptokey:
```
$ gcloud --project PROJECT_ID kms keyrings create KEYRING_NAME --location global

$ gcloud --project PROJECT_ID kms keys create parse --location global --keyring KEYRING_NAME --purpose encryption

$ gcloud --project PROJECT_ID kms keys add-iam-policy-binding parse --location global \
--keyring KEYRING_NAME --member serviceAccount:KEYRING_NAME@PROJECT_ID.iam.gserviceaccount.com \
--role roles/cloudkms.cryptoKeyEncrypterDecrypter
```

You will also need to grant the project service account access to decrypt the keys for this implementation. You could use a more secure setup if you would like.
```
gcloud --project PROJECT_ID kms keys add-iam-policy-binding parse --location global \
--keyring KEYRING_NAME --member serviceAccount:PROJECT_ID@appspot.gserviceaccount.com \
--role roles/cloudkms.cryptoKeyDecrypter
```

If you haven't used the KMS service before the SDK will error with a URL to go to to enable:
```
$ gcloud --project PROJECT_ID kms keyrings create KEYRING_NAME --location global
ERROR: (gcloud.kms.keyrings.create) FAILED_PRECONDITION: Google Cloud KMS API has not been used in this project before, or it is disabled. Enable it by visiting https://console.developers.google.com/apis/api/cloudkms.googleapis.com/overview?project=... then retry. If you enabled this API recently, wait a few minutes for the action to propagate to our systems and retry.
```

Once that is completed, navigate to `kms > api-client` in the GCP Samples repository and create a `doit.sh` with the following content:
```
PROJECTID="PROJECT_ID"
LOCATION=global
KEYRING=KEYRING_NAME
CRYPTOKEY=CRYPTOKEY_NAME
echo 'THE_SECRET' > /tmp/test_file
python snippets.py encrypt $PROJECTID $LOCATION $KEYRING $CRYPTOKEY \
  /tmp/test_file /tmp/test_file.encrypted 
python snippets.py decrypt $PROJECTID $LOCATION $KEYRING $CRYPTOKEY \
  /tmp/test_file.encrypted /tmp/test_file.decrypted
cat /tmp/test_file.decrypted
```

Fill in the `PROJECT_ID` from Google, the `KEYRING_NAME` you chose above, and `THE_SECRET` to encrypt.

Before you run the script you need to set the environment variable `GOOGLE_APPLICATION_CREDENTIALS` to the path of `key.json` that you generated previously.

This will look something like:
```
export GOOGLE_APPLICATION_CREDENTIALS=FOO/BAR/BEZ/key.json
```

If you now run `bash doit.sh` it should print the API Key and the Encrypted version should be stored in `/tmp/test_file.encrypted`. You can copy this file to somewhere else to temporarily store before we upload and then run the same script with the `parse` API Secret. In the below example I have renamed the file to `parse.encrypted`.

2) Upload Secrets

Once you have the encrypted secret file you will need to upload it to Google Cloud Storage for fetching in App Engine (and eventual decryption). Assuming the file is called `parse.encrypted`, you would run something like the following:
```
$ gsutil mb -p PROJECT_ID gs://BUCKET_NAME
Creating gs://BUCKET_NAME/...

$ gsutil cp parse.encrypted gs://BUCKET_NAME/keys/

$ gsutil ls gs://BUCKET_NAME/keys
<BOTH FILES SHOULD BE LISTED HERE>
```

## Building

Initially, you will need to install the dependencies into a `lib` directory with the following command:
```
pip install -t lib -r requirements.txt
```

This `lib` directory is excluded from `git`.

## Local Development

The included `dev_appserver.py` loaded into your `PATH` is the best/easiest way to test before deployment ([doc](https://cloud.google.com/appengine/docs/standard/python/tools/using-local-server)).

It can easily be launched with:
```
dev_appserver.py app.yaml
```

And then view `http://localhost:8000/cron` to run the `cron` locally. For this to work you will need to mock the KMS/GCS fetches otherwise you will get a 403 on the call to GCS bucket.

## Deploying

This might be the easiest thing you own / operate as is the case with many things that are built to run on GCP.

Deploy:
```
$ gcloud --project PROJECT_ID app deploy
$ gcloud --project PROJECT_ID app deploy cron.yaml
```

On your first run if this is the first App Engine application you will be prompted to choose a region.

## Testing

No unit tests at this time.

Once deployed, you can hit the `/run` path on the URL.

## Logging

Google's Stackdriver service is sufficient for the logging needs of this service.

To view logs, you can use the `gcloud` CLI:
```
$ gcloud --project PROJECT_ID app logs read --service=default --limit 10
```

If you are not using the `default` project, you will need to change that parameter.

If you want to view the full content of the logs you can use the beta `logging` command:
```
$ gcloud beta logging read "resource.type=gae_app AND logName=projects/[PROJECT_ID]/logs/appengine.googleapis.com%2Frequest_log" --limit 10 --format json
```

Filling in the appropriate `[PROJECT_ID]` from GCP.

You can also see all available logs with the following command:
```
gcloud beta logging logs list
```

## Cost

Most of the pieces here cost money and doing some quick math to make sure you are comfortable with the costs likely makes sense.

Parse: Depending on how you are running Parse, there may be costs to making these requests.

Google Cloud Platform: The App Engine Standard Environment has three costs associated with it for this project.

1) Compute: Per-instance hour cost ([here](https://cloud.google.com/appengine/pricing#standard_instance_pricing)).
2) Network: Outgoing network traffic ([here](https://cloud.google.com/appengine/pricing#other-resources)).
3) Key Management Service: Key versions + Key use operations ([here](https://cloud.google.com/kms/#cloud-kms-pricing)).

## Limits

Parse API: Consult your documentation on your deployment for any limits.

## Pull Requests

Sure, but please give me some time.

## License

Apache 2.0.

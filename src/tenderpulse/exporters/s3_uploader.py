def upload_to_s3(data, bucket, key):
    return {"status": "uploaded", "bucket": bucket, "key": key}

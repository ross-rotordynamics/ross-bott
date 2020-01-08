"""Utility functions."""
import os
import boto3


def upload_to_s3(file_name):
    S3_BUCKET = os.environ.get("S3_BUCKET")
    s3 = boto3.client("s3")
    s3.upload_file(file_name, S3_BUCKET, file_name)

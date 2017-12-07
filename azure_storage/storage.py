import mimetypes
import magic
import datetime

from azure.common import AzureMissingResourceHttpError
from azure.storage.blob import BlobService

from django.core.files.storage import Storage
from django.conf import settings

try:
    from django.utils.deconstruct import deconstructible
except ImportError:
    # Support for django 1.7 and below
    def deconstructible(func):
        return func


@deconstructible
class AzureStorage(Storage):
    """
    Custom file storage system for Azure
    """

    container = settings.AZURE_STORAGE.get('CONTAINER')
    account_name = settings.AZURE_STORAGE.get('ACCOUNT_NAME')
    account_key = settings.AZURE_STORAGE.get('ACCOUNT_KEY')
    cdn_host = settings.AZURE_STORAGE.get('CDN_HOST')
    use_ssl = settings.AZURE_STORAGE.get('USE_SSL')
    max_age = settings.AZURE_STORAGE.get('MAX_AGE')

    def __init__(self, account_name=None, account_key=None, container=None,
         use_ssl=None, cdn_host=None):

        if account_name is not None:
            self.account_name = account_name

        if account_key is not None:
            self.account_key = account_key

        if container is not None:
            self.container = container

        if use_ssl is not None:
            self.use_ssl = use_ssl

        if cdn_host is not None:
            self.cdn_host = cdn_host

    def __getstate__(self):
        return dict(
            account_name=self.account_name,
            account_key=self.account_key,
            container=self.container,
            cdn_host=self.cdn_host,
            use_ssl=self.use_ssl
        )

    def _get_service(self):
        if not hasattr(self, '_blob_service'):
            self._blob_service = BlobService(
                account_name=self.account_name,
                account_key=self.account_key,
                protocol='https' if self.use_ssl else 'http'
            )

        return self._blob_service

    def _get_properties(self, name):
        return self._get_service().get_blob_properties(
            container_name=self.container,
            blob_name=name
        )

    def _open(self, name, mode='rb'):
        """
        Return the AzureStorageFile.
        """

        from django.core.files.base import ContentFile

        contents = self._get_service().get_blob_to_bytes(
            container_name=self.container,
            blob_name=name
        )

        return ContentFile(contents)

    def _save(self, name, content):
        """
        Use the Azure Storage service to write ``content`` to a remote file
        (called ``name``).
        """
        

        content.open()

        content_type = None

        if hasattr(content.file, 'content_type'):
            content_type = content.file.content_type
        else:
            content_type = mimetypes.guess_type(name)[0]

        cache_control = self.get_cache_control(
            self.container,
            name,
            content_type
        )

        self._get_service().put_block_blob_from_file(
            container_name=self.container,
            blob_name=name,
            stream=content,
            x_ms_blob_content_type=content_type,
            cache_control=cache_control,
            x_ms_blob_cache_control=cache_control
        )

        content.close()

        return name

    def listdir(self, path):
        """
        Lists the contents of the specified path, returning a 2-tuple of lists;
        the first item being directories, the second item being files.
        """

        files = []

        if path and not path.endswith('/'):
            path = '%s/' % path

        path_len = len(path)

        if not path:
            path = None

        blob_list = self._get_service().list_blobs(self.container, prefix=path)

        for name in blob_list:
            files.append(name[path_len:])

        return ([], files)

    def exists(self, name):
        """
        Returns True if a file referenced by the given name already exists in
        the storage system, or False if the name is available for a new file.
        """
        try:
            self._get_properties(name)

            return True
        except AzureMissingResourceHttpError:
            return False

    def delete(self, name):
        """
        Deletes the file referenced by name.
        """

        try:
            self._get_service().delete_blob(self.container, name)
        except AzureMissingResourceHttpError:
            pass

    def get_cache_control(self, container, name, content_type):
        """
        Get the Cache-Control value for a blob, used when saving the blob on
        Azure.  Returns `None` by default to remain compatible with the
        default setting for the SDK.
        """
        if self.max_age is not None:
            return 'max-age=%s' % self.max_age

    def size(self, name):
        """
        Returns the total size, in bytes, of the file referenced by name.
        """

        try:
            properties = self._get_properties(name)

            return int(properties['content-length'])
        except AzureMissingResourceHttpError:
            pass

    def url(self, name):
        """
        Returns the URL where the contents of the file referenced by name can
        be accessed.
        """

        blob_url_args = {
            'container_name': self.container,
            'blob_name': name,
        }

        if self.cdn_host:
            # The account name should be built into the cdn hostname
            blob_url_args['account_name'] = ''
            blob_url_args['host_base'] = self.cdn_host

        return self._get_service().make_blob_url(
            **blob_url_args
        )

    def modified_time(self, name):
        """
        Returns a datetime object containing the last modified time.
        """

        try:
            properties = self._get_properties(name)

            return datetime.datetime.strptime(
                properties['last-modified'],
                '%a, %d %b %Y %H:%M:%S %Z'
            )
        except AzureMissingResourceHttpError:
            pass

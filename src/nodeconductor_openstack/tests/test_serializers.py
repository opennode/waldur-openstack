import unittest

from rest_framework import serializers

from nodeconductor.core import utils as core_utils
from nodeconductor_openstack.fields import StringTimestampField


class StringTimestampSerializer(serializers.Serializer):
    content = StringTimestampField(formats=('%Y-%m-%dT%H:%M:%S',))


class StringTimestampFieldTest(unittest.TestCase):
    def setUp(self):
        self.datetime = core_utils.timeshift()
        self.datetime_str = self.datetime.strftime('%Y-%m-%dT%H:%M:%S')
        self.timestamp = core_utils.datetime_to_timestamp(self.datetime)

    def test_datetime_string_serialized_as_timestamp(self):
        serializer = StringTimestampSerializer(instance={'content': self.datetime_str})
        actual = serializer.data['content']
        self.assertEqual(self.timestamp, actual)

    def test_timestamp_parsed_as_datetime_string(self):
        serializer = StringTimestampSerializer(data={'content': self.timestamp})
        self.assertTrue(serializer.is_valid())
        actual = serializer.validated_data['content']
        self.assertEqual(self.datetime_str, actual)

    def test_incorrect_timestamp(self):
        serializer = StringTimestampSerializer(data={'content': 'NOT_A_UNIX_TIMESTAMP'})
        self.assertFalse(serializer.is_valid())
        self.assertIn('content', serializer.errors,
                      'There should be errors for content field')
        self.assertIn('Value "NOT_A_UNIX_TIMESTAMP" should be valid UNIX timestamp.',
                      serializer.errors['content'])

    def test_incorrect_datetime_string(self):
        datetime_str = self.datetime.strftime('%Y-%m-%d')
        serializer = StringTimestampSerializer(instance={'content': datetime_str})

        with self.assertRaises(serializers.ValidationError):
            serializer.data['content']

    def test_field_initialization_without_formats(self):
        with self.assertRaises(AssertionError):
            StringTimestampField()

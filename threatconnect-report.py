# Copyright 2016 ThreatConnect, Inc.
# Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#      http://www.apache.org/licenses/LICENSE-2.0
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
"""
ThreatConnect reporting module for Cuckoo version 1.2.

This module creates an incident in ThreatConnect representing the analysis, and then imports all
network indicators found by Cuckoo and associates those indicators with the analysis.
"""

import datetime
import re

import ipaddress
import threatconnect

from lib.cuckoo.common.abstracts import Report
from lib.cuckoo.common.exceptions import CuckooReportError


def ip(indicator):
    """Check if an indicator is an IP address or not."""
    try:
        ipaddress.ip_address(indicator)
    except ValueError:
        return False
    else:
        return True


class ThreatConnectReport(Report):
    """Reports indicators from analysis results to an instance of ThreatConnect."""

    def create_incident(self):
        """Create an incident to represent the analysis in ThreatConnect.

        @raise CuckooReportError: if fails to write report.
        """

        # Instantiate an incidents object
        incidents = self.tc.incidents()

        # Get todays date and the filename of the analysis target
        date_today = datetime.date.today().strftime('%Y%m%d')
        if self.results.get('target').get('file').get('name'):
            filename = self.results['target']['file']['name']

        # Build a title for the incident
        title = 'Cuckoo Analysis {}: {}'.format(date_today, filename)

        # Add the title to the object
        incident = incidents.add(title, self.target_source)

        # Get the full timestamp for the current time and set the event date
        date_today_iso = datetime.datetime.now().isoformat()
        incident.set_event_date(date_today_iso)

        # Add the analysis ID to an attribute
        if self.results.get('info').get('id'):
            analysis_id = self.results.get('info').get('id')
        incident.add_attribute('Analysis ID', analysis_id)

        # Build a report link and record it in the Source attribute
        report_link = self.report_link_template.format(analysis_id)
        incident.add_attribute('Source', report_link)

        # Commit the changes to ThreatConnect
        try:
            incident.commit()
        except RuntimeError as e:
            raise CuckooReportError('Failed to commit incident: {}'.format(e))
        else:
            # Load the attributes into the incident object
            incident.load_attributes()

            # Mark all Cuckoo attributes with DO NOT SHARE security label
            for attribute in incident.attributes:
                if attribute.type == 'Analysis ID' or attribute.type == 'Source':
                    attribute.add_security_label('DO NOT SHARE')

            # Commit the changes to ThreatConnect
            try:
                incident.commit()
            except RuntimeError as e:
                raise CuckooReportError('Failed to commit incident: {}'.format(e))
            else:
                return incident.id

    def upload_indicator(self, raw_indicator):
        """Upload one indicator to ThreatConnect."""
        indicators = self.tc.indicators()
        indicator = indicators.add(raw_indicator, self.target_source)
        indicator.associate_group(threatconnect.ResourceType.INCIDENTS, self.incident_id)

        # Commit the changes to ThreatConnect
        try:
            indicator.commit()
        except RuntimeError as e:
            if not re.search('exclusion list', e):
                raise CuckooReportError('Failed to commit indicator: {}'.format(e))

    def import_network(self, type):
        """Loop through all connections and import all source and destination indicators.

        @param incident_id: Analysis incident ID.
        @param type: protocol, tcp or udp
        @raise CuckooReportError: if fails to write indicator.
        """
        for conn in self.results.get('network', dict()).get(type, dict()):

            # Import the source
            try:
                self.upload_indicator(conn.get('src'))
            except (CuckooReportError, RuntimeError):
                pass

            # Import the destination
            try:
                self.upload_indicator(conn.get('dst'))
            except (CuckooReportError, RuntimeError):
                pass

    def import_network_http(self):
        """Loop through all HTTP network connections and import all HTTP indicators.

        @param incident_id: Analysis incident ID.
        @raise CuckooReportError: if fails to write indicator.
        """
        # Loop through all HTTP network connections
        for conn in self.results.get('network', dict()).get('http', dict()):

            # Remove port number from host
            host = re.sub(':\d+', '', conn.get('host'))

            # Check if the host is an IP address
            if ip(host):
                try:
                    self.upload_indicator(host)
                except (CuckooReportError, RuntimeError):
                    pass

            # Import the URL indicator
            if conn.get('uri'):
                try:
                    self.upload_indicator(conn.get('uri'))
                except (CuckooReportError, RuntimeError):
                    pass

    def import_network_hosts(self):
        """Loop through all network hosts and import all network host indicators.

        @param incident_id: Analysis incident ID.
        @raise CuckooReportError: if fails to write indicator.
        """
        for host in self.results.get('network', dict()).get('hosts', dict()):

            # Check if the host is an IP address
            if ip(host):
                try:
                    self.upload_indicator(host)
                except (CuckooReportError, RuntimeError):
                    pass

            else:
                try:
                    self.upload_indicator(host)
                except (CuckooReportError, RuntimeError):
                    pass

    def import_network_dns(self):
        """Loop through all DNS connections and import all request and answer indicators.

        @param incident_id: Analysis incident ID.
        @raise CuckooReportError: if fails to write indicator.
        """
        # Loop through all DNS request connections
        for conn in self.results.get('network', dict()).get('dns', dict()):

            # Record the DNS request
            try:
                self.upload_indicator(conn.get('request'))
            except (CuckooReportError, RuntimeError):
                pass

            # Record all the answers
            for answer in conn.get('answers', list()):
                try:
                    self.upload_indicator(answer)
                except (CuckooReportError, RuntimeError):
                    pass

    def import_network_domains(self):
        """Loop through all domains and import everything as host and address indicators.

        @param incident_id: Analysis incident ID.
        @raise CuckooReportError: if fails to write indicator.
        """
        for domain in self.results.get('network', dict()).get('domains', dict()):

            # If an IP is available, import it
            if domain.get('ip'):
                try:
                    self.upload_indicator(domain.get('ip'))
                except (CuckooReportError, RuntimeError):
                    pass

            # If domain is available, import it
            if domain.get('domain'):
                try:
                    self.upload_indicator(domain.get('domain'))
                except (CuckooReportError, RuntimeError):
                    pass

    def import_file(self):
        """Import file indicator.

        @param incident_id: Analysis incident ID.
        @raise CuckooReportError: if fails to write indicator.
        """
        if self.results.get('target').get('category') == 'file':
            if self.results.get('target').get('file'):

                indicators = self.tc.indicators()

                file_data = self.results.get('target').get('file')

                # Import all the hashes
                indicator = indicators.add(file_data.get('md5'), self.target_source)
                indicator.set_indicator(file_data.get('sha1'))
                indicator.set_indicator(file_data.get('sha256'))

                # Set the file size
                indicator.set_size(file_data.get('size'))

                # If there is a started time, set this as a file occurrence along with the filename
                if self.results.get('info').get('started'):
                    fo_date = self.results.get('info').get('started')[:10]
                    indicator.add_file_occurrence(file_data.get('name'), fo_date=fo_date)

                indicator.associate_group(threatconnect.ResourceType.INCIDENTS, self.incident_id)

                # Commit the changes to ThreatConnect
                try:
                    indicator.commit()
                except RuntimeError as e:
                    if not re.search('exclusion list', e):
                        raise CuckooReportError('Failed to commit indicator: {}'.format(e))

    def run(self, results):
        """Upload indicators and incident via ThreatConnect SDK.

        @param results: Cuckoo results dict.
        """
        api_access_id = self.options.api_access_id
        api_secret_key = self.options.api_secret_key
        api_base_url = self.options.api_base_url
        self.target_source = self.options.target_source
        self.tc = threatconnect.ThreatConnect(api_access_id, api_secret_key,
                                              self.options.target_source, api_base_url)
        self.report_link_template = self.options.report_link_template
        self.results = results

        self.incident_id = self.create_incident()

        self.import_network('udp')
        self.import_network('tcp')
        self.import_network_http()
        self.import_network_hosts()
        self.import_network_dns()
        self.import_network_domains()
        try:
            self.import_file()
        except (CuckooReportError, RuntimeError):
            pass

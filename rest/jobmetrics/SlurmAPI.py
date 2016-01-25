#!flask/bin/python
# -*- coding: utf-8 -*-
#
# Copyright (C) 2015-2016 EDF SA
#
# This file is part of jobmetrics.
#
# jobmetrics is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# jobmetrics is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with jobmetrics.  If not, see <http://www.gnu.org/licenses/>.

import json
import requests
from requests.exceptions import ConnectionError

class SlurmAPI(object):

    def __init__(self, conf, cluster, cache):

        self.cluster = cluster
        self.base_url = conf.api(cluster)
        self.cache = cache
        self.auth_login = conf.login(cluster)
        self.auth_password = conf.password(cluster)

        if cache.empty is None:
            self.auth_token = None
            self.auth_enabled = None
            self.auth_guest = None
        else:
            self.auth_token = cache.token
            self.auth_enabled = cache.auth_enabled
            self.auth_guest = cache.auth_guest

    @property
    def auth_as_guest(self):

        return self.auth_login == 'guest'

    def check_auth(self):

        url = "{base}/authentication".format(base=self.base_url)
        try:
            resp = requests.get(url=url)
        except ConnectionError, err:
            # reformat the exception
            raise ConnectionError("connection error while trying to connect " \
                                  "to {url}: {error}" \
                                    .format(url=url, error=err))

        try:
            json_auth = json.loads(resp.text)
        except ValueError:
            # reformat the exception
            raise ValueError("not JSON data for GET {url}" \
                               .format(url=url))

        self.auth_enabled = json_auth['enabled']
        self.auth_guest = json_auth['guest']

    def login(self):

        url = "{base}/login".format(base=self.base_url)
        try:
            if self.auth_as_guest is True:
                payload = { "guest": True }
            else:
                payload = { "username": self.auth_login,
                            "password": self.auth_password }
            resp = requests.post(url=url, json=payload)
        except ConnectionError, err:
            # reformat the exception
            raise ConnectionError("connection error while trying to connect " \
                                  "to {url}: {error}" \
                                    .format(url=url, error=err))

        if resp.status_code != 200:
            raise Exception("login failed with {code} on API {api}" \
                               .format(code=resp.status_code,
                                       api=self.base_url))
        try:
            login = json.loads(resp.text)
        except ValueError:
            # reformat the exception
            raise ValueError("not JSON data for POST {url}" \
                               .format(url=url))

        self.auth_token = login['id_token']

    def ensure_auth(self):

        # If cache was able to give us a token, assume auth is enable, the
        # token is still valid and use it straightfully. If the token is not
        # valid according to slurm-web, the error will be handled then.
        if self.auth_token is not None:
            return

        # if auth_enabled is None, it means the cache was not able to tell us.
        # In this case, we have to check ourselves.
        if self.auth_enabled is None:
            self.check_auth()
            # update the cache with new data
            self.cache.auth_enabled = self.auth_enabled
            self.cache.auth_guest = self.auth_guest

        # if the auth is disable, go on with it.
        if self.auth_enabled is False:
            return

        # At this point, auth is enabled and we do not have token.

        # First check if the app is configured to log as guest and guest login
        # is enable.
        if self.auth_as_guest and self.auth_guest is False:
            raise Exception("unable to log as guest to {base}" \
                              .format(base=self.base_url))

        self.login()
        # update token in cache
        self.cache.token = self.auth_token

    def job_params(self, job, firsttime=True):
        """Request the Slurm REST API of the cluster to get Job params. Raises
           IndexError if job is not found or ValueError if not well formatted
           JSON data sent by the API.
        """

        self.ensure_auth()

        url = "{base}/job/{job}" \
                  .format(base=self.base_url,
                          job=job)
        try:
            if self.auth_enabled is True:
                payload = { 'token': self.auth_token }
                resp = requests.post(url=url, json=payload)
            else:
                resp = requests.post(url=url)
        except ConnectionError, err:
            # reformat the exception
            raise ValueError("connection error while trying to connect to " \
                             "{url}: {error}".format(url=url, error=err))

        if resp.status_code == 404:
            raise IndexError("job ID {jobid} not found in API {api}" \
                               .format(jobid=job, api=self.base_url))

        if resp.status_code == 403:
            if firsttime:
                # We probably get this error because of invalidated token.
                # Invalidate cache, trigger check_auth() and call this method
                # again.
                self.auth_token = None
                self.auth_enabled = None
                self.cache.invalidate()
                return self.job_params(job, firsttime=False)
            else:
                # We have already tried twice. This means the app is not able
                # to auth on slurm-web API with current params. Just throw the
                # error and give-up here.
                raise Exception("get 403/forbidden from {url} with new token" \
                                  .format(url=self.base_url))
        try:
            json_job = json.loads(resp.text)
        except ValueError:
            # reformat the exception
            raise ValueError("not JSON data for GET {url}" \
                               .format(url=url))
        return json_job
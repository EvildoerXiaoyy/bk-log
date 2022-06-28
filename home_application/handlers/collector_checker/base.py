# -*- coding: utf-8 -*-
"""
Tencent is pleased to support the open source community by making BK-LOG 蓝鲸日志平台 available.
Copyright (C) 2021 THL A29 Limited, a Tencent company.  All rights reserved.
BK-LOG 蓝鲸日志平台 is licensed under the MIT License.
License for BK-LOG 蓝鲸日志平台:
--------------------------------------------------------------------
Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
documentation files (the "Software"), to deal in the Software without restriction, including without limitation
the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software,
and to permit persons to whom the Software is furnished to do so, subject to the following conditions:
The above copyright notice and this permission notice shall be included in all copies or substantial
portions of the Software.
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT
LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN
NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
We undertake not to change the open source license (MIT license) applicable to the current version of
the project delivered to anyone in the future.
"""
import sys
import json

from apps.log_databus.models import CollectorConfig


class Report(object):
    def __init__(self, name, info: list = None, warning: list = None, error: list = None):
        self.name = name
        self.info = info if info else []
        self.warning = warning if warning else []
        self.error = error if warning else []

    def has_problem(self):
        return self.error != []

    def add_info(self, message: str):
        self.info.append(message)

    def add_warning(self, message: str):
        self.warning.append(message)

    def add_error(self, message: str):
        self.error.append(message)

    def add_report(self, report):
        self.info.extend(report.info)
        self.warning.extend(report.warning)
        self.error.extend(report.error)

    def __str__(self):
        return json.dumps(
            {"report_name": self.name, "info": self.info, "warning": self.warning, "error": self.error},
            ensure_ascii=False,
        )


class BaseStory(object):
    name = ""

    def __init__(self):
        self.hosts = []
        for i in sys.argv:
            if "collector_config_id" in i:
                collector_config_id = i.split("=")[1]
                self.collector_config = CollectorConfig.objects.get(collector_config_id=collector_config_id)
                continue
            if "hosts" in i:
                try:
                    # "0:ip1,0:ip2,1:ip3"
                    ip_list = []
                    hosts = i.split("=")[1].split(",")
                    for host in hosts:
                        ip_list.append({"bk_cloud_id": int(host.split(":")[0]), "ip": host.split(":")[1]})
                    self.hosts = ip_list
                except Exception as e:  # pylint: disable=broad-except
                    raise Exception(f"输入合法的hosts, err: {str(e)}")

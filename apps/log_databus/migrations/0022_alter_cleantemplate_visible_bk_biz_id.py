# Generated by Django 3.2.5 on 2022-04-21 12:41

import apps.models
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("log_databus", "0021_auto_20220415_1205"),
    ]

    operations = [
        migrations.AlterField(
            model_name="cleantemplate",
            name="visible_bk_biz_id",
            field=apps.models.MultiStrSplitByCommaFieldText(default="", verbose_name="可见业务ID"),
        ),
    ]

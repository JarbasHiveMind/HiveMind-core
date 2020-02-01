from setuptools import setup

setup(
    name='jarbas_hive_mind',
    version='0.5.0',
    packages=['jarbas_hive_mind',
              'jarbas_hive_mind.master',
              'jarbas_hive_mind.slave',
              'jarbas_hive_mind.configuration',
              'jarbas_hive_mind.database',
              'jarbas_hive_mind.utils'],
    include_package_data=True,
    install_requires=["pyopenssl",
                      "service_identity",
                      "autobahn",
                      "twisted",
                      "jarbas_utils>=0.4.1",
                      "json_database",
                      "sqlalchemy"],
    url='https://github.com/JarbasAl/hive_mind',
    license='MIT',
    author='jarbasAI',
    author_email='jarbasai@mailfence.com',
    description='Mesh Networking utilities for mycroft core'
)

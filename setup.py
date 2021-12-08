from setuptools import setup

setup(
    name='jarbas_hive_mind',
    version='0.10.9',
    packages=['jarbas_hive_mind',
              'jarbas_hive_mind.nodes',
              'jarbas_hive_mind.configuration',
              'jarbas_hive_mind.database',
              'jarbas_hive_mind.utils',
              'jarbas_hive_mind.discovery',
               # below are deprecated, backwards compat only
              'jarbas_hive_mind.master',
              'jarbas_hive_mind.slave'],
    include_package_data=True,
    install_requires=["pyopenssl",
                      "service_identity",
                      "autobahn",
                      "twisted",
                      "mycroft-messagebus-client>=0.9.1",
                      "ovos_utils>=0.0.6",
                      "json_database>=0.2.6",
                      "pycryptodomex",
                      "HiveMind_presence~=0.0.2a2"],
    url='https://github.com/JarbasAl/hive_mind',
    license='MIT',
    author='jarbasAI',
    author_email='jarbasai@mailfence.com',
    description='Mesh Networking utilities for mycroft core',
    entry_points={
        'console_scripts': [
            'HiveMind-server=jarbas_hive_mind.__main__:main',
            'HiveMind-database=jarbas_hive_mind.database.__main__:main'
        ]
    }
)

import os
from pathlib import Path

from ruamel.yaml import YAML

from deployer.infra_components.cluster import Cluster
from deployer.utils.file_acquisition import get_all_cluster_yaml_files

yaml = YAML(typ="safe", pure=True)

REPO_ROOT_PATH = Path(__file__).parent
CONFIG_CLUSTERS_PATH = REPO_ROOT_PATH.joinpath("config/clusters")


def get_cluster_names():
    cluster_names = []
    for config_file_path in get_all_cluster_yaml_files():
        with open(config_file_path) as f:
            cluster = Cluster(yaml.load(f), config_file_path.parent)
        cluster_names.append(os.path.basename(config_file_path.parent))

    cluster_names = sorted(cluster_names)
    # cluster_names = ["2i2c-aws-us"]  # limit to one cluster for testing
    return cluster_names


def main():
    cluster_names = get_cluster_names()

    gh_auth_list = []
    for c in cluster_names:
        gh_auth = False
        cluster = Cluster.from_name(c)
        print(f"Checking cluster {cluster.spec.get('name')}")
        for hub in cluster.hubs:
            print(f"Checking hub {hub.spec.get('name')}")
            values_files = hub.spec.get("helm_chart_values_files")
            # Ignore encrypted files and reorder to check common files last since hub-specific files may override them.
            values_files = [
                f for f in values_files if ("common" not in f) and ("enc" not in f)
            ] + [f for f in values_files if ("common" in f) and ("enc" not in f)]
            for vf in values_files:
                print(vf)
                with open(CONFIG_CLUSTERS_PATH / c / vf) as f:
                    value_config = yaml.load(f)
                    if "basehub" in value_config.keys():
                        value_config = value_config["basehub"]
                    if "common" not in vf:
                        print(f"Checking {vf} for {hub.spec.get('name')}")
                        try:
                            authenticator_class = value_config["jupyterhub"]["hub"][
                                "config"
                            ]["JupyterHub"]["authenticator_class"]
                        except KeyError:
                            continue
                        gh_auth = True if authenticator_class == "github" else False
                        print(f"{gh_auth}")
                        break
                    else:
                        print(f"Checking common {vf} for {hub.spec.get('name')}")
                        try:
                            authenticator_class = value_config["jupyterhub"]["hub"][
                                "config"
                            ]["JupyterHub"]["authenticator_class"]
                        except KeyError:
                            continue
                        gh_auth = True if authenticator_class == "github" else False
                        print(f"{gh_auth}")
            gh_auth_list.append([c, hub.spec.get("name"), gh_auth])


if __name__ == "__main__":
    main()

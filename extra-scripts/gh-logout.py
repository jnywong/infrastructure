"""
A script to force one-time logout of GitHub authenticated users.
"""

import logging
import os
import subprocess
from pathlib import Path

from ruamel.yaml import YAML

from deployer.infra_components.cluster import Cluster
from deployer.utils.file_acquisition import get_all_cluster_yaml_files

logger = logging.getLogger(__name__)

yaml = YAML(typ="safe", pure=True)

REPO_ROOT_PATH = Path(__file__).parent.parent
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


def get_gh_auth_hubs(cluster_names: list[str]) -> list[list[str]]:
    """
    Return a list of clusters and hubs that use GitHub authentication.
    """
    hubs_list = []
    for c in cluster_names:
        gh_auth = False
        cluster = Cluster.from_name(c)
        logger.debug(f"Checking cluster {cluster.spec.get('name')}")
        for hub in cluster.hubs:
            logger.debug(f"Checking hub {hub.spec.get('name')}")
            values_files = hub.spec.get("helm_chart_values_files")
            # Ignore encrypted files and reorder to check common files last since hub-specific files may override them.
            values_files = [
                f for f in values_files if ("common" not in f) and ("enc" not in f)
            ] + [f for f in values_files if ("common" in f) and ("enc" not in f)]
            for vf in values_files:
                logger.debug(vf)
                with open(CONFIG_CLUSTERS_PATH / c / vf) as f:
                    value_config = yaml.load(f)
                    if "basehub" in value_config.keys():
                        value_config = value_config["basehub"]
                    if "common" not in vf:
                        logger.debug(f"Checking {vf} for {hub.spec.get('name')}")
                        try:
                            authenticator_class = value_config["jupyterhub"]["hub"][
                                "config"
                            ]["JupyterHub"]["authenticator_class"]
                        except KeyError:
                            continue
                        gh_auth = True if authenticator_class == "github" else False
                        logger.debug(f"{gh_auth}")
                        break
                    else:
                        logger.debug(f"Checking common {vf} for {hub.spec.get('name')}")
                        try:
                            authenticator_class = value_config["jupyterhub"]["hub"][
                                "config"
                            ]["JupyterHub"]["authenticator_class"]
                        except KeyError:
                            continue
                        gh_auth = True if authenticator_class == "github" else False
                        logger.debug(f"{gh_auth}")
            hubs_list.append([c, hub.spec.get("name"), gh_auth])
    gh_auth_hubs = [item[:2] for item in hubs_list if item[2] is True]
    logger.debug(
        f"Number of GitHub authenticated hubs = ({len(gh_auth_hubs)}/{len(hubs_list)})"
    )
    return gh_auth_hubs


def write_to_text_file(hubs_list: list[list[str]], file_name: str):
    """
    Write the list of GitHub authenticated hubs to a text file.
    """
    with open(file_name, "w") as f:
        for hub in hubs_list:
            f.write(f"{hub}\n")
    logger.info(f"GitHub authenticated hubs written to {file_name}")


def read_from_text_file(file_name: str) -> list[str]:
    """
    Read the list of GitHub authenticated hubs from a text file.
    """
    with open(file_name) as f:
        hubs_list = [tuple(eval(line.strip())) for line in f.readlines()]
    logger.info(f"Read {len(hubs_list)} GitHub authenticated hubs from {file_name}")
    return hubs_list


def remove_from_text_file(cluster_name: str, hub_name: str, file_name: str):
    """
    Remove a specific cluster and hub from the text file.
    """
    with open(file_name) as f:
        lines = f.readlines()

    with open(file_name, "w") as f:
        for line in lines:
            if not (f"['{cluster_name}', '{hub_name}']" in line):
                f.write(line)
    logger.info(f"Removed {cluster_name}:{hub_name} from {file_name}")


def log_out_from_hub(gh_auth_hubs: list[tuple[str, str]], file_name: str):
    for cluster_name, hub_name in gh_auth_hubs:
        logger.debug(f"Logging users out of {cluster_name}:{hub_name}")
        cluster = Cluster.from_name(cluster_name)

        with cluster.auth():
            # Determine if the hub has user pods running
            has_users = False
            get_pod = subprocess.check_output(
                [
                    "kubectl",
                    "-n",
                    hub_name,
                    "get",
                    "pod",
                ]
            )
            has_users = True if "jupyter-" in get_pod.decode() else False
            (
                logger.info(f"{cluster_name}:{hub_name} - User pods found.")
                if has_users
                else logger.info(f"{cluster_name}:{hub_name} - No user pods found.")
            )
            if has_users:
                pass
            else:
                # Delete hub.config.JupyterHub.cookie_secret
                output_delete_secret = subprocess.check_output(
                    [
                        "kubectl",
                        "-n",
                        hub_name,
                        "patch",
                        "secret",
                        "hub",
                        "--type=json",
                        "-p=[{'op': 'remove', 'path': '/data/hub.config.JupyterHub.cookie_secret'}]",
                    ]
                )
                logger.info(output_delete_secret.decode().strip())
                # Deploy hub to regenerate cookie_secret
                output_deployer_deploy = subprocess.check_output(
                    [
                        "deployer",
                        "deploy",
                        cluster_name,
                        hub_name,
                    ]
                )
                logger.debug(output_deployer_deploy.decode().strip())
                logger.info(f"{cluster_name}:{hub_name} - redeployed.")
        remove_from_text_file(cluster_name, hub_name, file_name)


def main():
    logging.basicConfig(
        filename="gh_logout.log",
        filemode="w",
        level=logging.DEBUG,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )

    file_name = "gh_auth_hubs.txt"

    if not os.path.exists(file_name):
        cluster_names = get_cluster_names()
        logger.info(f"Found clusters: {cluster_names}")
        gh_auth_hubs = get_gh_auth_hubs(cluster_names)
        write_to_text_file(gh_auth_hubs, file_name)
    gh_auth_hubs = read_from_text_file(file_name)
    logger.info(f"GitHub authenticated hubs: {gh_auth_hubs}")

    # Test hubs
    gh_auth_hubs = [
        # ("leap", "prod"),
        ("2i2c-aws-us", "staging"),
    ]

    log_out_from_hub(gh_auth_hubs, file_name)


if __name__ == "__main__":
    main()

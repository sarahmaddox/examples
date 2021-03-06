"""Some utitilies for running notebook tests."""

import datetime
import logging
import uuid
import yaml

from kubernetes import client as k8s_client
from kubeflow.testing import argo_build_util
from kubeflow.testing import util

def run_papermill_job(name, namespace, # pylint: disable=too-many-branches,too-many-statements
                      repos, image):
  """Generate a K8s job to run a notebook using papermill

  Args:
    name: Name for the K8s job
    namespace: The namespace where the job should run.
    repos: (Optional) Which repos to checkout; if not specified tries
      to infer based on PROW environment variables
    image:
  """

  util.maybe_activate_service_account()

  with open("job.yaml") as hf:
    job = yaml.load(hf)

  # We need to checkout the correct version of the code
  # in presubmits and postsubmits. We should check the environment variables
  # for the prow environment variables to get the appropriate values.
  # We should probably also only do that if the
  # See
  # https://github.com/kubernetes/test-infra/blob/45246b09ed105698aa8fb928b7736d14480def29/prow/jobs.md#job-environment-variables
  if not repos:
    repos = argo_build_util.get_repo_from_prow_env()

  logging.info("Repos set to %s", repos)
  job["spec"]["template"]["spec"]["initContainers"][0]["command"] = [
    "/usr/local/bin/checkout_repos.sh",
    "--repos=" + repos,
    "--src_dir=/src",
    "--depth=all",
  ]
  job["spec"]["template"]["spec"]["containers"][0]["image"] = image
  util.load_kube_config(persist_config=False)

  if name:
    job["metadata"]["name"] = name
  else:
    job["metadata"]["name"] = ("xgboost-test-" +
                               datetime.datetime.now().strftime("%H%M%S")
                               + "-" + uuid.uuid4().hex[0:3])
    name = job["metadata"]["name"]

  job["metadata"]["namespace"] = namespace

  # Create an API client object to talk to the K8s master.
  api_client = k8s_client.ApiClient()
  batch_api = k8s_client.BatchV1Api(api_client)

  logging.info("Creating job:\n%s", yaml.dump(job))
  actual_job = batch_api.create_namespaced_job(job["metadata"]["namespace"],
                                               job)
  logging.info("Created job %s.%s:\n%s", namespace, name,
               yaml.safe_dump(actual_job.to_dict()))

  final_job = util.wait_for_job(api_client, namespace, name,
                                timeout=datetime.timedelta(minutes=30))

  logging.info("Final job:\n%s", yaml.safe_dump(final_job.to_dict()))

  if not final_job.status.conditions:
    raise RuntimeError("Job {0}.{1}; did not complete".format(namespace, name))

  last_condition = final_job.status.conditions[-1]

  if last_condition.type not in ["Complete"]:
    logging.error("Job didn't complete successfully")
    raise RuntimeError("Job {0}.{1} failed".format(namespace, name))

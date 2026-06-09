# OpenShift AI Boundary

PBS v0.3.0 does not manage OpenShift AI by default. OpenShift AI resources, model serving endpoints,
LLM provider credentials, and inference services should be installed by OpenShift AI lifecycle
manifests or GitOps owned outside the PBS Operator.

PBS may consume endpoints and secret references exposed by that lifecycle through ConfigMaps and
Secrets, but Phase 1 does not create, delete, patch, or validate live OpenShift AI resources.

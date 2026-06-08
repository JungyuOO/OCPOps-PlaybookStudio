# OpenShift Lightspeed Integration Boundary

PBS v0.3.0 does not own the OpenShift Lightspeed Operator lifecycle. This directory is reserved for
declarative integration previews that PBS or a future PBS Operator can generate after the Lightspeed
Operator is installed by its own lifecycle.

The base currently contains the narrow ingress NetworkPolicy PBS needs to call the Lightspeed API
from the `pbs-ocpops` namespace. It does not install or mutate the Lightspeed Operator itself.

Apply these files only during an approved live validation or GitOps sync window because they change
the `openshift-lightspeed` namespace traffic boundary.

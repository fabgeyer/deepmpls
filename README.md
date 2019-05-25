# DeepMPLS: Fast Analysis of MPLS Configurations Using Deep Learning

This repository contains part of the code used for the paper _"DeepMPLS: Fast Analysis of MPLS Configurations Using Deep Learning"_ published at the [IFIP Networking 2019](https://networking.ifip.org/2019/) conference. For access to the dataset, please refer to the [dataset repository](https://github.com/fabgeyer/dataset-networking2019). The tools currently only supports the query types specified in the DeepMPLS paper.


## Installation

```
$ git clone --recursive https://github.com/fabgeyer/deepmpls.git
$ cd deepmpls
$ pip install -r P-Rex/requirements.txt
```


## Example usage

The repository contains a simple command line utility for transforming MPLS networks to their graph representation. It uses the XML file format used by P-Rex for representing the topology and the MPLS configuration.

Usage:
```
$ python graph_transformation.py <topo.xml> <routing.xml> '<a> b <c>' k
```

Example:
```
$ python graph_transformation.py P-Rex/test/test_cli/1/topo.xml P-Rex/test/test_cli/1/routing.xml '<.*> s1 .* s7 <>' 2
```


## Citation

If you use this code for your research, please include the following reference in any resulting publication:

```bibtex
@inproceedings{GeyerSchmid_Networking2019,
	author    = {Geyer, Fabien and Schmid, Stefan},
	title     = {{DeepMPLS}: Fast Analysis of MPLS Configurations Using Deep Learning},
	booktitle = {Proceedings of the 18th IFIP Networking Conference},
	year      = {2019},
	month     = mai,
	address   = {Warsaw, Poland},
}
```

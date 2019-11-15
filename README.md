# DeepMPLS: Fast Analysis of MPLS Configurations Using Deep Learning

This repository contains part of the code for the paper [_"DeepMPLS: Fast Analysis of MPLS Configurations Using Deep Learning"_](https://dx.doi.org/10.23919/IFIPNetworking.2019.8816842) published at the [IFIP Networking 2019](https://networking.ifip.org/2019/) conference. For access to the dataset only, please refer to the [dataset repository](https://github.com/fabgeyer/dataset-networking2019). The tools currently only supports the query types specified in the DeepMPLS paper.


## Installation

The dataset is stored in the [dataset repository](https://github.com/fabgeyer/dataset-networking2019) using [git lfs](https://git-lfs.github.com/). Install git lfs on your system first and then clone the code and dataset repository using:

```
$ git lfs clone --recursive https://github.com/fabgeyer/deepmpls.git
$ cd deepmpls
```

To install the required python dependencies, use:
```
$ pip3 install -r requirements.txt
```


## Example usage

### Query prediction using GNN model

The repository contains an implementation of the Graph Neural Network used in the paper based on [PyTorch Geometric](https://pytorch-geometric.readthedocs.io). Currently the neural network can only be used to predict the satisfiability of a query.

Usage for training on the paper's dataset:
```
$ python3 neural_network_qpred.py
```

In order to only partially load the dataset, the `nnetworks` argument can be used to specify the number of networks to load:
```
$ python3 neural_network_qpred.py --nnetworks 10
```


### Graph transformation

The repository contains also a simple command line utility for transforming MPLS networks to their DeepMPLS graph representation. It uses the XML file format used by P-Rex for representing the topology and the MPLS configuration.

Usage:
```
$ python3 graph_transformation.py <topo.xml> <routing.xml> '<a> b <c>' k
```

Example:
```
$ python3 graph_transformation.py P-Rex/test/test_cli/1/topo.xml P-Rex/test/test_cli/1/routing.xml '<.*> s1 .* s7 <>' 2
```


## Citation

If you use this code for your research, please include the following reference in any resulting publication:

```bibtex
@inproceedings{GeyerSchmid_Networking2019,
	author    = {Geyer, Fabien and Schmid, Stefan},
	title     = {{DeepMPLS}: Fast Analysis of {MPLS} Configurations Using Deep Learning},
	booktitle = {Proceedings of the 18th IFIP Networking Conference},
	year      = {2019},
	month     = mai,
	address   = {Warsaw, Poland},
	doi       = {10.23919/IFIPNetworking.2019.8816842},
}
```

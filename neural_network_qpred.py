#!/usr/bin/env python3
"""
Copyright (c) 2019 Fabien Geyer

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

import os
import re
import sys
import glob
import gzip
import json
import tarfile
import argparse
import numpy as np
import networkx as nx
import multiprocess as mp
from tqdm import tqdm, trange

import torch
import torch.nn as nn
import torch_geometric.nn as gnn
from torch_geometric.data import Data, DataLoader

sys.path.insert(0, 'P-Rex')
from prex.prnml import xml
from graph_transformation import mpls2graph, NodeType


class GNNModel(gnn.MessagePassing):
    def __init__(self, num_features, num_classes, args):
        super(GNNModel, self).__init__()
        # First layers
        self.fci = nn.Sequential(*[
            nn.Linear(num_features, args.hidden_size),
            nn.LeakyReLU(),
            nn.Dropout(args.dropout),
        ])

        self.cell = gnn.GatedGraphConv(args.hidden_size, args.nunroll)

        # Final layers
        self.fco = nn.Sequential(*[
            nn.Linear(args.hidden_size, args.hidden_size),
            nn.LeakyReLU(),
            nn.Dropout(args.dropout),
            nn.Linear(args.hidden_size, num_classes),
        ])

    def forward(self, data):
        x = self.fci(data.x)
        x = self.cell(x, data.edge_index)
        x = self.fco(x)
        return x


def graph2torch(G):
    """
    Transforms a networkx graph generated by `mpls2graph` to its matrix representation.
    Returns a torch_geometric.data.Data object
    """

    # Unique id for each node in the graph
    ids = dict(zip(G.nodes(), range(G.number_of_nodes())))

    # Node features
    x = torch.zeros((G.number_of_nodes(), len(NodeType)))
    # Label corresponds here to the prediction of the query output
    y = torch.zeros(G.number_of_nodes(), dtype=torch.int64)
    # Mask used for selecting the query node in the loss function.
    # See torch.index_select(...) in training function
    mask = torch.zeros(G.number_of_nodes(), dtype=torch.bool)

    for node, data in G.nodes(data=True):
        nid = ids[node]
        x[nid, data["ntype"] - 1] = 1  # One-hot encoding of node type

        if "pred" in data:
            y[nid] = data["pred"]
            mask[nid] = True

    edge_index = torch.zeros((2, G.number_of_edges() * 2), dtype=torch.int64)
    i = 0
    for src, dst in G.edges():
        # Each edge from the undirected graph G is encoded as two directed edges
        edge_index[0, i] = ids[src]
        edge_index[1, i] = ids[dst]
        i += 1
        edge_index[0, i] = ids[dst]
        edge_index[1, i] = ids[src]
        i += 1

    return Data(x=x, edge_index=edge_index, y=y, mask=mask)


def graph2torch_worker(networks, qwork, qresults):
    while True:
        query = qwork.get()
        if query is None:
            break
        q, k = re.search(r"^(.+)\s([0-9]+)$", query["query"]).groups()
        G = mpls2graph(networks[query["network"]], q, int(k))
        G.nodes[NodeType.Query]["pred"] = query["query_result"]
        data = graph2torch(G)
        qresults.put(data)


def prepare_dataset(args, netfiles, tqdm_desc):
    dataset = []
    mgr = mp.Manager()
    qwork = mgr.Queue()
    qresults = mgr.Queue()

    for netfile in tqdm(netfiles, ncols=0, desc=tqdm_desc):
        # First parse the tar file and the networks it contains
        tar = tarfile.open(netfile, "r")
        networks = {}
        network_names = set(map(lambda n: os.path.split(n)[0], tar.getnames()))
        for name in tqdm(network_names, desc="Parse networks", ncols=0, leave=False):
            topo = tar.extractfile(os.path.join(name, "topo.xml"))
            routing = tar.extractfile(os.path.join(name, "routing.xml"))
            networks[name] = xml.read_network(topo, routing)
            topo.close()
            routing.close()
        tar.close()

        # Start workers for processing and building the graphs in parallel
        workers = []
        for _ in range(mp.cpu_count()):
            worker = mp.Process(target=graph2torch_worker, args=(networks, qwork, qresults))
            worker.start()
            workers.append(worker)

        # Parse queries and their results
        jsonfile = netfile.replace(".xmls.tgz", ".queries.json.gz")
        with open(jsonfile, "r") as f:
            queries = json.load(f)

        # Push queries to workers
        nqueries = 0
        for query in queries:
            qwork.put(query)
            nqueries += 1

        # Send None to notify workers that there's no more work
        for _ in range(len(workers)):
            qwork.put(None)

        for _ in trange(nqueries, ncols=0, desc="Build graphs", leave=False):
            dataset.append(qresults.get())

        # Shutdown workers
        for worker in workers:
            worker.join()

    mgr.shutdown()
    return dataset


def main(args):
    # Initialize random seeds
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)

    # Find dataset files and split them in train and eval
    netfiles = sorted(glob.glob(args.dataset_path))
    if args.nnetworks < 2:
        netfiles = np.array(netfiles)
    else:
        netfiles = np.array(netfiles[:args.nnetworks])

    train_mask = np.random.rand(len(netfiles)) < args.train_test_split
    if np.all(train_mask):
        # Make sure that we have at least one dataset for evaluation
        train_mask[np.random.randint(len(netfiles))] = False

    # Parse dataset and transforms it to graph objects
    dataset_train = prepare_dataset(args, netfiles[train_mask], "Build train dataset")
    dataset_eval = prepare_dataset(args, netfiles[~train_mask], "Build eval dataset")
    loader_train = DataLoader(dataset_train, batch_size=args.batch_size)
    loader_eval = DataLoader(dataset_eval, batch_size=args.batch_size)
    print(f"Dataset size: train={len(dataset_train)} eval={len(dataset_eval)}")

    if args.cpu:
        device = torch.device("cpu")
    else:
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        torch.cuda.manual_seed(args.seed)

    # Initialize model
    model = GNNModel(len(NodeType), 2, args)
    model = model.to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=args.learning_rate)
    criterion = nn.CrossEntropyLoss()

    # Main loop
    for epoch in trange(args.epochs, ncols=0):
        losses_train = []
        metrics_train = []
        metrics_eval = []

        # Train model on training data
        model.train()
        for data in loader_train:
            optimizer.zero_grad()
            output = model(data.to(device))

            # Select only the relevant nodes for the loss function
            idxmask = torch.where(data.mask)[0]
            mlabels = torch.index_select(data.y, 0, idxmask)
            moutput = torch.index_select(output, 0, idxmask)

            loss = criterion(moutput, mlabels)
            losses_train.append(loss.item())
            loss.backward()
            optimizer.step()

            choices = torch.argmax(moutput, axis=1)
            metric = choices == mlabels
            metrics_train.extend(metric.tolist())

        # Use model on eval data
        model.eval()
        for data in loader_eval:
            with torch.no_grad():
                output = model(data.to(device))

            idxmask = torch.where(data.mask)[0]
            mlabels = torch.index_select(data.y, 0, idxmask)
            moutput = torch.index_select(output, 0, idxmask)

            choices = torch.argmax(moutput, axis=1)
            metric = choices == mlabels
            metrics_eval.extend(metric.tolist())

        tqdm.write(f"{epoch:3d} | loss={np.mean(losses_train):.2e} metric={np.mean(metrics_train)*100:.2f} | test={np.mean(metrics_eval)*100:.2f}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--seed", type=int, default=1, help="Seed used for random number generator")
    p.add_argument("--dataset-path", type=str, default="dataset-networking2019/dataset/qpred/*/*.xmls.tgz")
    p.add_argument("--nnetworks", type=int, default=0, help="Number of networks to load (0=all)")
    p.add_argument("--epochs", type=int, default=15, help="Number of epochs for training")
    p.add_argument("--learning-rate", type=float, default=5e-4, help="Learning rate for Adam")
    p.add_argument("--dropout", type=float, default=.5, help="Dropout used for between the linear layers")
    p.add_argument("--train-test-split", type=float, default=.75)
    p.add_argument("--batch-size", type=int, default=16, help="Batch size")
    p.add_argument("--hidden-size", type=int, default=64, help="Size of the hidden messages")
    p.add_argument("--nunroll", type=int, default=10, help="Number of loop unrolling for the Gated Graph NN")
    p.add_argument("--cpu", action="store_true", help="Disable use of GPU")
    args = p.parse_args()
    main(args)

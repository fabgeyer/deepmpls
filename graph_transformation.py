#!/usr/bin/env python3

import io
import sys
import enum
import argparse
import networkx as nx

sys.path.insert(0, 'P-Rex')
from prex.prnml import model
from prex.prnml import xml
from prex.util import keydefaultdict
from prex.lang.prex import *

NodeType = enum.IntEnum("NodeType", [
    "Router",
    "Interface",
    "Label",
    "Rule",
    "PushAction",
    "SwapAction",
    "PopAction",
    "Query",
    "QueryAtom",
    "Any",
    "OneOrMore",
    "ZeroOrMore",
])


def ensure_label_nodes(G, st):
    """
    Traverses the list of atoms given by 'st' and adds the missing labels to the graph
    """
    if st is None:
        return

    for atom in st.getAtoms():
        if isinstance(atom, ASimpleAtom):
            symb = atom.getSymbol()
        elif isinstance(atom, AQuantifiedAtom):
            atom_ = atom.getAtom()
            if isinstance(atom_, ASimpleAtom):
                symb = atom_.getSymbol()
            else:
                continue
        else:
            continue

        lbl = str(symb).strip()
        lbl = xml.get_label(lbl)
        if lbl not in G.nodes:
            G.add_node(lbl, ntype=NodeType.Label, nlabel=f"label:{lbl.name}")


def atom_label_to_node(G, atom):
    if isinstance(atom, ASimpleAtom):
        lbl = str(atom.getSymbol()).strip()
        lbl = xml.get_label(lbl)
        assert lbl in G.nodes
        G.add_node(atom, ntype=NodeType.QueryAtom, nlabel=f"atom:label:{lbl.name}")
        G.add_edge(atom, lbl)
        return atom

    elif isinstance(atom, AAnyAtom):
        G.add_node(atom, ntype=NodeType.Label, nlabel="atom:any")
        return atom

    else:
        raise Exception(f"Unknown atom type: {type(atom)}")


def build_labels_graph_repr(G, lastnode, st):
    """
    Transform the regular expression defining a set of labels in its graph representation
    Note: This function currently handles only simple regular expressions.
    """

    if st is None:
        G.add_node("empty", ntype=NodeType.Label, nlabel="label:empty")
        G.add_edge(lastnode, "empty")
        return "empty"

    par_nodes = []
    lastatom = None
    branch_next = False
    for atom in st.getAtoms():
        if isinstance(atom, AQuantifiedAtom):
            quantifier = atom.getQuantifier()
            if isinstance(lastatom, ASimpleAtom):
                # XXX: This function only handles simple regular expressions
                raise Exception("Case not covered by code")

            elif isinstance(quantifier, AZeroOrMoreQuantifier) and isinstance(atom.getAtom(), AAnyAtom):
                G.add_node(atom, ntype=NodeType.ZeroOrMore, nlabel="atom:label:.*")
                G.add_edge(lastnode, atom)
                lastnode = atom

            elif isinstance(quantifier, AOneOrMoreQuantifier) and isinstance(atom.getAtom(), AAnyAtom):
                G.add_node(atom, ntype=NodeType.OneOrMore, nlabel="atom:label:.+")
                G.add_edge(lastnode, atom)
                lastnode = atom

            elif isinstance(quantifier, AOneOrMoreQuantifier):
                node = atom_label_to_node(G, atom.getAtom())
                G.add_edge(lastnode, node)
                par_nodes.append(node)
                branch_next = True

            else:
                raise Exception(f"Unknown quantifier type: {type(quantifier)}")

        else:
            node = atom_label_to_node(G, atom)
            if branch_next:
                G.add_edge(lastnode, node)
                par_nodes.append(node)
                branch_next = False

            elif len(par_nodes) > 0:
                for n in par_nodes:
                    G.add_edge(n, node)
                par_nodes = []
                lastnode = node

            else:
                G.add_edge(lastnode, node)
                lastnode = node

        lastatom = atom

    if len(par_nodes) > 0:
        return par_nodes
    return lastnode


def mpls2graph(net, query, k):
    """
    Transforms a network object from the P-Rex tool and a given query into its graph representation
    Returns a networkx graph. Each node has the attributes `ntype` for its type, and `nlabel` for its label.

    Arguments:
        net (prex.prnml.Model): topology and MPLS configuration
        query (str): query to evaluate in the form of '<a> b <c>'
        k (int): number specifying the maximum allowed number of failed links
    """

    G = nx.Graph()

    name2router = {}
    for rtr in net.topology.routers:
        name2router[rtr.name] = rtr
        # One node per router
        G.add_node(rtr, ntype=NodeType.Router, nlabel=f"router:{rtr.name}")
        for iface in rtr.interfaces.values():
            # One node per interface, connected to its corresponding router
            G.add_node(iface, ntype=NodeType.Interface, nlabel=f"intf:{rtr.name}:{iface.name}")
            G.add_edge(rtr, iface)

    for lnk in net.topology.links:
        # Edges represent links between interfaces
        G.add_edge(lnk.from_.interface, lnk.to.interface)

    G.add_node(xml.get_label(None), ntype=NodeType.Label, nlabel=f"label:none")
    for lbl in net.routing.collect_labels():
        # One node per label
        G.add_node(lbl, ntype=NodeType.Label, nlabel=f"label:{lbl.name}")

    for rtr, table in net.routing.routingTables:
        i = 0
        for _, dest in table.destinations.items():
            rule = dest.te_groups[0].rules[0]
            G.add_node(rule, ntype=NodeType.Rule, nlabel=f"{rtr.name}:rule{i}")
            G.add_edge(rule, rule.from_)  # Input interface
            if not isinstance(rule.label, model.NoLabel):
                G.add_edge(rule, rule.label)

            last = rule
            for j, action in enumerate(rule.actions):
                if isinstance(action, model.PushAction):
                    G.add_node(action, ntype=NodeType.PushAction, nlabel=f"{rtr.name}:rule{i}:action{j}:PUSH")
                    G.add_edge(action, action.label)

                elif isinstance(action, model.SwapAction):
                    G.add_node(action, ntype=NodeType.SwapAction, nlabel=f"{rtr.name}:rule{i}:action{j}:SWAP")
                    G.add_edge(action, action.label)

                elif isinstance(action, model.PopAction):
                    G.add_node(action, ntype=NodeType.PopAction, nlabel=f"{rtr.name}:rule{i}:action{j}:POP")

                else:
                    raise Exception(f"Unknown action type: {type(action)}")

                G.add_edge(last, action)
                last = action

            # Connect the last action to the output interface
            G.add_edge(last, rule.to)
            i += 1

    # Parse query using lexer from P-Rex
    lexer = Lexer(io.StringIO(query))
    parser = Parser(lexer)
    query_ast = parser.parse().getPQuery()

    constr = query_ast.getConstructing()  # AST of the '<a>' part of the query
    destr = query_ast.getDestructing()  # AST of the '<c>' part of the query

    # Make sure that all labels are in the graph
    ensure_label_nodes(G, constr)
    ensure_label_nodes(G, destr)

    # Special node representing the query
    G.add_node(NodeType.Query, ntype=NodeType.Query, nlabel="query", k=k)
    last = NodeType.Query

    # Add the '<a>' part of the query to the graph
    last = build_labels_graph_repr(G, NodeType.Query, constr)

    # Add the 'b' part of the query to the graph
    for atom in query_ast.getNetwork().getAtoms():
        if isinstance(atom, ASimpleAtom):
            rtr = str(atom.getSymbol()).strip()
            G.add_node(atom, ntype=NodeType.QueryAtom, nlabel=f"atom:router:{rtr}")
            if rtr not in name2router:
                G.add_node(rtr, ntype=NodeType.Router, nlabel=rtr)
            else:
                rtr = name2router[rtr]

            if isinstance(last, list):
                for l in last:
                    G.add_edge(l, atom)
            else:
                G.add_edge(last, atom)
            G.add_edge(atom, rtr)
            last = atom

        elif isinstance(atom, AQuantifiedAtom):
            quantifier = atom.getQuantifier()
            if isinstance(quantifier, AOneOrMoreQuantifier) and isinstance(atom.getAtom(), AAnyAtom):
                G.add_node(atom, ntype=NodeType.ZeroOrMore, nlabel="atom:router:.*")

            elif isinstance(quantifier, AZeroOrMoreQuantifier) and isinstance(atom.getAtom(), AAnyAtom):
                G.add_node(atom, ntype=NodeType.OneOrMore, nlabel="atom:router:.+")

            else:
                raise Exception(f"Unknown atom: {type(atom.getAtom())} quantifier={type(quantifier)}")

            if isinstance(last, list):
                for l in last:
                    G.add_edge(l, atom)
            else:
                G.add_edge(last, atom)
            last = atom

        elif isinstance(atom, AAnyAtom):
            G.add_node(atom, ntype=NodeType.Any, nlabel="router:.")

            if isinstance(last, list):
                for l in last:
                    G.add_edge(l, atom)
            else:
                G.add_edge(last, atom)
            last = atom

        else:
            raise Exception(f"Unknown atom type: {type(atom)}")

    # Add the '<c>' part of the query to the graph
    build_labels_graph_repr(G, last, destr)
    return G


# ----------------------------------------------------------------------------


def main(args):
    with open(args.topology, "r") as topoh:
        with open(args.routing, "r") as routingh:
            net = xml.read_network(topoh, routingh)

    G = mpls2graph(net, args.query, args.k)

    # Debug function to print all edges from the graph
    for src, dst in G.edges():
        print(G.node[src]['nlabel'], "--", G.node[dst]['nlabel'])


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("topology", type=str)
    p.add_argument("routing", type=str)
    p.add_argument("query", type=str)
    p.add_argument("k", type=int)
    args = p.parse_args()
    main(args)

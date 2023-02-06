from pathlib import Path
import os
import numpy as np
import pandas as pd
from tqdm import tqdm
import torch.nn.functional as F
import random

import torch
from sklearn.metrics import r2_score
from sklearn.model_selection import train_test_split
from torch_geometric.loader import DataLoader
from torch_geometric.nn import GCNConv, SAGEConv, GATConv
from model import FeatureSteeredConvolution, MeshProcessingNetwork, ResGNN, DenseGNN, JKNet
from datasets.in_memory import IMDataset
import wandb

REGISTERED_ROOT = "/data1/practical-wise2223/registered_5" # the path of the dir saving the .ply registered data
INMEMORY_ROOT = '/data1/practical-wise2223/registered5_gender_seperation_root' # the root dir path to save all the artifacts ralated of the InMemoryDataset
FEATURES_PATH = "/vol/chameleon/projects/mesh_gnn/basic_features.csv"
TARGET = "age"

def train(model, trainloader, valloader, device, config):
    
    if config["task"]== "regression" :
        loss_criterion = torch.nn.MSELoss()
    elif config["task"]== "classification": 
        loss_criterion = torch.nn.CrossEntropyLoss()

    loss_criterion.to(device)

    optimizer = torch.optim.Adam(model.parameters(), lr=config['learning_rate'], weight_decay=config['weight_decay'])

    model.train()

    best_accuracy = 0.
    train_loss_running = 0.

    for epoch in range(config['epochs']):
        for i, data in tqdm(enumerate(trainloader)):  
            data = data.to(device)
            optimizer.zero_grad()
            prediction = model(data)
            label = data.y.to(device)
            loss = loss_criterion(prediction, label)  
            loss.to(device)
            loss.backward()
            optimizer.step()
            
            # loss logging
            train_loss_running += loss.item()
            iteration = epoch * len(trainloader) + i

            if iteration % config['print_every_n'] == (config['print_every_n'] - 1):
                print(f'[{epoch:03d}/{i:05d}] train_loss: {train_loss_running / config["print_every_n"]:.3f}')
                wandb.log({"training loss": train_loss_running / config["print_every_n"]})
                train_loss_running = 0.
                
            # validation evaluation and logging
            if iteration % config['validate_every_n'] == (config['validate_every_n'] - 1):

                loss_total_val = 0
                _predictions = torch.tensor([])
                _labels = torch.tensor([])

                # set model to eval, important if your network has e.g. dropout or batchnorm layers
                model.eval()
                
                # forward pass and evaluation for entire validation set
                for val_data in valloader:
                    val_data = val_data.to(device)
                    
                    with torch.no_grad():
                        # Get prediction scores
                        if config["task"] == "classification":
                            prediction = F.softmax(model(val_data).detach().cpu(), dim=1)
                        elif config["task"] == "regression":
                            prediction = model(val_data).detach().cpu()
                                  
                    val_label = val_data.y.detach().cpu()
                    #keep track of loss_total_val                                  
                    loss_total_val += loss_criterion(prediction,val_label).item()
                    _predictions = torch.cat((_predictions.double(), prediction.double()))
                    _labels = torch.cat((_labels.double(), val_label.double()))

                if config["task"] == "classification":
                    accuracy = np.mean((torch.argmax(_predictions,1)==torch.argmax(_labels,1)).numpy())
                elif config["task"] == "regression":
                    accuracy = r2_score(_labels, _predictions)

                print(f'[{epoch:03d}/{i:05d}] val_loss: {loss_total_val / len(valloader):.3f}, val_accuracy: {accuracy:.3f}')
                wandb.log({"validation loss": loss_total_val / len(valloader), "validation accuracy": accuracy })
                if accuracy > best_accuracy:
                    torch.save(model.state_dict(), f'runs/{config["experiment_name"]}/model_best.ckpt')
                    best_accuracy = accuracy

                # set model back to train
                model.train()

def test(model, loader, device, task):
    model.eval()
 
    crit = torch.nn.MSELoss() if task == "regression" else torch.nn.CrossEntropyLoss()
    predictions = torch.tensor([])
    targets = torch.tensor([])
    
    with torch.no_grad():
        for data in loader:
            data = data.to(device)
            pred = model(data).detach().cpu() if task == "regression" else F.softmax(model(data).detach().cpu(), dim=1)
            target = data.y.detach().cpu()
            predictions = torch.cat((predictions, pred))
            targets = torch.cat((targets, target))

    loss = crit(predictions, targets)
    acc = r2_score(targets, predictions) if task == "regression" else np.mean((torch.argmax(predictions,1)==torch.argmax(targets,1)).numpy())

    return loss, acc

def main():    
    dataset_female = IMDataset(REGISTERED_ROOT, INMEMORY_ROOT, FEATURES_PATH, TARGET, 0)
    dataset_male = IMDataset(REGISTERED_ROOT, INMEMORY_ROOT, FEATURES_PATH, TARGET, 1)

    dev_data_female, test_data_female = train_test_split(dataset_female, test_size=0.1, random_state=42, shuffle=True)
    train_data_female, val_data_female = train_test_split(dev_data_female, test_size=0.33, random_state=43, shuffle=True)
    dev_data_male, test_data_male = train_test_split(dataset_male, test_size=0.1, random_state=42, shuffle=True)
    train_data_male, val_data_male = train_test_split(dev_data_male, test_size=0.33, random_state=43, shuffle=True)

    train_data_all = train_data_male + train_data_female
    val_data_all = val_data_male + val_data_female
    test_data_all = test_data_male + test_data_female
    random.shuffle(train_data_all)
    random.shuffle(val_data_all)
    random.shuffle(test_data_all)

    config = {
        "experiment_name" : "age_prediction_5k", # there should be a folder named exactly this under the folder runs/
        "batch_size" : 32,
        "epochs" : 2000,
        "learning_rate" : 0.005,
        "weight_decay": 0.01,
        "task" : "regression", # "regression" or "classification"
        "print_every_n" : 200,
        "validate_every_n" : 200}

    wandb.init(project = "mesh-gnn", config = config)
    
    n_class = 1 if config["task"] == "regression" else 2


# MeshProcressingNet params
    # model_params = dict(
    #     gnn_conv = GATConv,
    #     in_features = 3,
    #     encoder_channels = [16],
    #     conv_channels = [32, 64, 128, 64],
    #     decoder_channels = [32],
    #     num_classes = n_class,
    #     apply_dropedge = False,
    #     apply_bn = True,
    #     apply_dropout = False,
    #     num_heads=4
    # )


# ResGNN params
    # model_params = dict(
    #     gnn_conv = SAGEConv,
    #     in_features = 3,
    #     inout_conv_channel = 64,
    #     num_layers = 5,
    #     num_skip_layers = 1,
    #     encoder_channels = [1024],
    #     decoder_channels = [256, 64],
    #     num_classes = n_class,
    #     aggregation = 'max', # mean, max
    #     apply_dropedge = True,
    #     apply_bn = True,
    #     apply_dropout = True
    # )

# DenseGNN params
    # model_params = dict(
    #     gnn_conv = SAGEConv,
    #     in_features = 3,
    #     inout_conv_channel = 32,
    #     num_layers = 5,
    #     encoder_channels = [1024],
    #     decoder_channels = [256, 64],
    #     num_classes = n_class,
    #     aggregation = 'max', # mean, max
    #     apply_dropedge = True,
    #     apply_bn = True,
    #     apply_dropout = True,
    # )


# JKNet params
    model_params = dict(
        gnn_conv = SAGEConv,
        in_features = 3,
        num_classes = n_class,
    )

    torch.cuda.set_device(3)
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print("current GPU:", torch.cuda.get_device_name(device))
    print("using GPU:", torch.cuda.current_device())

    # model = MeshProcessingNetwork(**model_params).to(device) 
    # model = ResGNN(**model_params).to(device)
    # model = DenseGNN(**model_params).to(device)
    model = JKNet(**model_params).to(device)
    model = model.double()

    param_log = {
        'params':{
            'network': str(model),
            'config': str(config),
            'model_params': str(model_params),
        }
    }

    wandb.log({"table": pd.DataFrame(param_log)})

    train_loader = DataLoader(train_data_all, batch_size = config["batch_size"], shuffle = True)
    val_loader = DataLoader(val_data_all, batch_size = config["batch_size"], shuffle = True)
    # test_loader = DataLoader(test_data_all, batch_size = config["batch_size"])

    train(model, train_loader, val_loader, device, config)
    
if __name__ == "__main__":
    main()

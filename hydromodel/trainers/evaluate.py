"""
Author: Wenyu Ouyang
Date: 2022-10-25 21:16:22
LastEditTime: 2024-03-26 21:52:05
LastEditors: Wenyu Ouyang
Description: Plots for calibration and testing results
FilePath: \hydro-model-xaj\hydromodel\trainers\evaluate.py
Copyright (c) 2021-2022 Wenyu Ouyang. All rights reserved.
"""

import pathlib
import pandas as pd
import os
import numpy as np
import xarray as xr
import spotpy

from hydroutils import hydro_file
from hydrodata.utils.utils import streamflow_unit_conv

from hydromodel.datasets import FLOW_NAME, remove_unit_from_name
from hydromodel.datasets.data_preprocess import get_basin_area
from hydromodel.models.model_config import MODEL_PARAM_DICT
from hydromodel.models.xaj import xaj


def read_save_sceua_calibrated_params(basin_id, save_dir, sceua_calibrated_file_name):
    """
    read the parameters' file generated by spotpy SCE-UA when finishing calibration

    We also save the parameters of the best model run to a file

    Parameters
    ----------
    basin_id
        id of a basin
    save_dir
        the directory where we save params
    sceua_calibrated_file_name
        the parameters' file generated by spotpy SCE-UA when finishing calibration

    Returns
    -------

    """
    results = spotpy.analyser.load_csv_results(sceua_calibrated_file_name)
    bestindex, bestobjf = spotpy.analyser.get_minlikeindex(
        results
    )  # 结果数组中具有最小目标函数的位置的索引
    best_model_run = results[bestindex]
    fields = [word for word in best_model_run.dtype.names if word.startswith("par")]
    best_calibrate_params = pd.DataFrame(list(best_model_run[fields]))
    save_file = os.path.join(save_dir, basin_id + "_calibrate_params.txt")
    best_calibrate_params.to_csv(save_file, sep=",", index=False, header=True)
    return np.array(best_calibrate_params).reshape(1, -1)  # 返回一列最佳的结果


def read_all_basin_params(basins, save_dir):
    params_list = []
    for basin_id in basins:
        db_name = os.path.join(save_dir, basin_id)
        # 读取每个流域的参数
        basin_params = read_save_sceua_calibrated_params(basin_id, save_dir, db_name)
        # 确保basin_params是一维的
        basin_params = basin_params.flatten()
        params_list.append(basin_params)
    return np.vstack(params_list)


def convert_streamflow_units(test_data, qsim, data_type, data_dir):
    times = test_data["time"].data
    basins = test_data["basin"].data
    flow_name = remove_unit_from_name(FLOW_NAME)
    flow_dataarray = xr.DataArray(
        qsim.squeeze(-1), coords=[("time", times), ("basin", basins)], name=flow_name
    )
    flow_dataarray.attrs["units"] = test_data[flow_name].attrs["units"]
    ds = xr.Dataset()
    ds[flow_name] = flow_dataarray
    target_unit = "m^3/s"
    basin_area = get_basin_area(data_type, data_dir, basins)
    ds_simflow = streamflow_unit_conv(
        ds, basin_area, target_unit=target_unit, inverse=True
    )
    ds_obsflow = streamflow_unit_conv(
        test_data[[flow_name]], basin_area, target_unit=target_unit, inverse=True
    )
    return ds_simflow, ds_obsflow


def summarize_parameters(result_dir, model_name, basin_ids):
    """
    output parameters of all basins to one file

    Parameters
    ----------
    result_dir
        the directory where we save results
    model_name
        the name of the model

    Returns
    -------

    """
    params = []
    for basin_id in basin_ids:
        columns = MODEL_PARAM_DICT[model_name]["param_name"]
        params_txt = pd.read_csv(
            os.path.join(result_dir, basin_id + "_calibrate_params.txt")
        )
        params_df = pd.DataFrame(params_txt.values.T, columns=columns)
        params.append(params_df)
    params_dfs = pd.concat(params, axis=0)
    params_dfs.index = basin_ids
    print(params_dfs)
    params_dfs_ = params_dfs.transpose()
    params_csv_file = os.path.join(result_dir, "basins_params.csv")
    params_dfs_.to_csv(params_csv_file, sep=",", index=True, header=True)


def renormalize_params(result_dir, model_name, basin_ids):
    renormalization_params = []
    for basin_id in basin_ids:
        params = np.loadtxt(
            os.path.join(result_dir, basin_id + "_calibrate_params.txt")
        )[1:].reshape(1, -1)
        param_ranges = MODEL_PARAM_DICT[model_name]["param_range"]
        xaj_params = [
            (value[1] - value[0]) * params[:, i] + value[0]
            for i, (key, value) in enumerate(param_ranges.items())
        ]
        xaj_params_ = np.array([x for j in xaj_params for x in j])
        params_df = pd.DataFrame(xaj_params_.T)
        renormalization_params.append(params_df)
    renormalization_params_dfs = pd.concat(renormalization_params, axis=1)
    renormalization_params_dfs.index = MODEL_PARAM_DICT[model_name]["param_name"]
    renormalization_params_dfs.columns = basin_ids
    print(renormalization_params_dfs)
    params_csv_file = os.path.join(result_dir, "basins_renormalization_params.csv")
    renormalization_params_dfs.to_csv(params_csv_file, sep=",", index=True, header=True)


def summarize_metrics(result_dir, model_info: dict):
    """
    output all results' metrics of all basins to one file

    Parameters
    ----------
    result_dir
        the directory where we save results

    Returns
    -------

    """
    path = pathlib.Path(result_dir)
    all_basins_files = [file for file in path.iterdir() if file.is_dir()]
    train_metrics = {}
    test_metrics = {}
    count = 0
    basin_ids = []
    for basin_dir in all_basins_files:
        basin_id = basin_dir.stem
        basin_ids.append(basin_id)
        train_metric_file = os.path.join(basin_dir, "train_metrics.json")
        test_metric_file = os.path.join(basin_dir, "test_metrics.json")
        train_metric = hydro_file.unserialize_json(train_metric_file)
        test_metric = hydro_file.unserialize_json(test_metric_file)

        for key, value in train_metric.items():
            if count == 0:
                train_metrics[key] = value
            else:
                train_metrics[key] = train_metrics[key] + value
        for key, value in test_metric.items():
            if count == 0:
                test_metrics[key] = value
            else:
                test_metrics[key] = test_metrics[key] + value
        count = count + 1
    metric_dfs_train = pd.DataFrame(train_metrics, index=basin_ids).transpose()
    metric_dfs_test = pd.DataFrame(test_metrics, index=basin_ids).transpose()
    metric_file_train = os.path.join(result_dir, "basins_metrics_train.csv")
    metric_file_test = os.path.join(result_dir, "basins_metrics_test.csv")
    metric_dfs_train.to_csv(metric_file_train, sep=",", index=True, header=True)
    metric_dfs_test.to_csv(metric_file_test, sep=",", index=True, header=True)


def save_evaluate_results(result_dir, model_name, qsim, qobs, obs_ds):
    ds = xr.Dataset()

    # 添加 qsim 和 qobs
    ds["qsim"] = qsim["flow"]
    ds["qobs"] = qobs["flow"]

    # 添加 prcp 和 pet
    ds["prcp"] = obs_ds["prcp"]
    ds["pet"] = obs_ds["pet"]

    # 保存为 .nc 文件
    file_path = os.path.join(result_dir, f"{model_name}_evaluation_results.nc")
    ds.to_netcdf(file_path)

    print(f"Results saved to: {file_path}")


def read_and_save_et_ouputs(result_dir, fold: int):
    prameter_file = os.path.join(result_dir, "basins_params.csv")
    param_values = pd.read_csv(prameter_file, index_col=0)
    basins_id = param_values.columns.values
    args_file = os.path.join(result_dir, "args.json")
    args = hydro_file.unserialize_json(args_file)
    warmup_length = args["warmup_length"]
    model_func_param = args["model"]
    exp_dir = pathlib.Path(result_dir).parent
    data_info_train = hydro_file.unserialize_json(
        exp_dir.joinpath(f"data_info_fold{fold}_train.json")
    )
    data_info_test = hydro_file.unserialize_json(
        exp_dir.joinpath(f"data_info_fold{fold}_test.json")
    )
    train_period = data_info_train["time"]
    test_period = data_info_test["time"]
    # TODO: basins_lump_p_pe_q_fold NAME need to be unified
    train_np_file = os.path.join(exp_dir, f"data_info_fold{fold}_train.npy")
    test_np_file = os.path.join(exp_dir, f"data_info_fold{fold}_test.npy")
    # train_np_file = os.path.join(exp_dir, f"basins_lump_p_pe_q_fold{fold}_train.npy")
    # test_np_file = os.path.join(exp_dir, f"basins_lump_p_pe_q_fold{fold}_test.npy")
    train_data = np.load(train_np_file)
    test_data = np.load(test_np_file)
    es_test = []
    es_train = []
    for i in range(len(basins_id)):
        _, e_train = xaj(
            train_data[:, :, 0:2],
            param_values[basins_id[i]].values.reshape(1, -1),
            warmup_length=warmup_length,
            **model_func_param,
        )
        _, e_test = xaj(
            test_data[:, :, 0:2],
            param_values[basins_id[i]].values.reshape(1, -1),
            warmup_length=warmup_length,
            **model_func_param,
        )
        es_train.append(e_train.flatten())
        es_test.append(e_test.flatten())
    df_e_train = pd.DataFrame(
        np.array(es_train).T, columns=basins_id, index=train_period[warmup_length:]
    )
    df_e_test = pd.DataFrame(
        np.array(es_test).T, columns=basins_id, index=test_period[warmup_length:]
    )
    etsim_train_save_path = os.path.join(result_dir, "basin_etsim_train.csv")
    etsim_test_save_path = os.path.join(result_dir, "basin_etsim_test.csv")
    df_e_train.to_csv(etsim_train_save_path)
    df_e_test.to_csv(etsim_test_save_path)

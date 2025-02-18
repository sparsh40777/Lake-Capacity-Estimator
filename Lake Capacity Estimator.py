# -*- coding: utf-8 -*-
"""
/***************************************************************************
 LakeCapacityEstimator
                                 A QGIS plugin
 This plugin generates capacity of the lake at different lake levels.
 Generated by Plugin Builder: http://g-sherman.github.io/Qgis-Plugin-Builder/
                              -------------------
        begin                : 2025-02-18
        git sha              : $Format:%H$
        copyright            : (C) 2025 by Sparsh Shekhar
        email                : sparshshekhar4077@gmail.com
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""

import os
from qgis.core import (
    QgsRasterLayer, QgsProcessingAlgorithm, QgsProcessingParameterRasterLayer,
    QgsProcessingParameterBoolean, QgsProcessingParameterFileDestination, QgsProcessingParameterNumber,
    QgsProcessingParameterEnum
)
from osgeo import gdal
import numpy as np
import webbrowser
import pandas as pd
import matplotlib.pyplot as plt
from io import BytesIO

class RasterDepthAnalysis(QgsProcessingAlgorithm):
    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterRasterLayer("INPUT_RASTER", "Input Raster"))
        self.addParameter(QgsProcessingParameterEnum("OUTPUT_FORMAT", "Output Format", options=["CSV"], defaultValue=0))
        self.addParameter(QgsProcessingParameterFileDestination("OUTPUT_CSV_FILE", "Output CSV File", "CSV Files (*.csv)"))
        self.addParameter(QgsProcessingParameterBoolean("SKIP_OUTPUT", "Skip Output", defaultValue=False))
        self.addParameter(QgsProcessingParameterNumber("INCREMENT", "Depth Interval Increment", type=QgsProcessingParameterNumber.Double, minValue=0.01, defaultValue=0.1))

    def processAlgorithm(self, parameters, context, feedback):
        raster_layer = self.parameterAsRasterLayer(parameters, "INPUT_RASTER", context)
        output_format = self.parameterAsEnum(parameters, "OUTPUT_FORMAT", context)
        output_csv_file = self.parameterAsFile(parameters, "OUTPUT_CSV_FILE", context)
        skip_output = self.parameterAsBoolean(parameters, "SKIP_OUTPUT", context)
        increment = self.parameterAsDouble(parameters, "INCREMENT", context)

        if not raster_layer or not raster_layer.isValid():
            raise ValueError("Invalid raster file")

        raster_path = raster_layer.source()
        dataset = gdal.Open(raster_path)
        band = dataset.GetRasterBand(1)
        raster_array = band.ReadAsArray().astype(np.float32)

        no_data_value = band.GetNoDataValue()
        if no_data_value is not None:
            raster_array[raster_array == no_data_value] = np.nan

        min_value = np.nanmin(raster_array)
        max_value = np.nanmax(raster_array)
        count_valid_pixels = np.sum(~np.isnan(raster_array))

        geo_transform = dataset.GetGeoTransform()
        pixel_size_x, pixel_size_y = geo_transform[1], -geo_transform[5]
        mean_resolution = (pixel_size_x + pixel_size_y) / 2

        depth_intervals = np.arange(0, max_value + increment, increment)
        depth_counts = [(depth, np.sum(raster_array >= depth)) for depth in depth_intervals]

        depth_data = [(depth, count, (count * mean_resolution**2) / 1e6) for depth, count in depth_counts]
        depth_data.reverse()

        volume_data = [0]
        for i in range(len(depth_data) - 1):
            h = increment
            A1 = depth_data[i][2]
            A2 = depth_data[i + 1][2]
            A_mid = (A1 * A2) ** 0.5
            volume = (h / 6) * (A1 + 4 * A_mid + A2)
            volume_data.append(volume)

        cumulative_volume_data = [0]
        for i in range(1, len(volume_data)):
            cumulative_volume_data.append(cumulative_volume_data[i - 1] + volume_data[i])

        depth_data = [(depth, count, area, vol, cum_vol, max_value - depth)
                      for (depth, count, area), vol, cum_vol
                      in zip(depth_data, volume_data, cumulative_volume_data)]

        if skip_output:
            return {}

        if output_format == 0:
            chart_path = output_csv_file.replace('.csv', '_chart.png')
            self.generate_csv(output_csv_file, min_value, max_value, count_valid_pixels,
                              pixel_size_x, pixel_size_y, mean_resolution, depth_data, chart_path)
        else:
            self.generate_pdf(output_pdf_file, min_value, max_value, count_valid_pixels,
                              pixel_size_x, pixel_size_y, mean_resolution, depth_data)

        return {"OUTPUT_FILE": output_pdf_file if output_format == 1 else output_csv_file}
    
    def generate_csv(self, csv_path, min_val, max_val, pixel_count, pixel_size_x, pixel_size_y, mean_resolution, depth_data, chart_path):
        df = pd.DataFrame(depth_data, columns=[
            "Depth Interval", "Pixel Count", "Area (km²)",
            "Volume (Million m³)", "Cumulative Volume (Million m³)",
            "Level from Bottom"
        ])
        self.generate_cumulative_volume_chart(chart_path, df)
        df.loc[0, "Chart Path"] = chart_path
        df.to_csv(csv_path, index=False)

    def generate_cumulative_volume_chart(self, chart_path, df):
        plt.figure(figsize=(6, 4))
        plt.plot(df["Cumulative Volume (Million m³)"], df["Level from Bottom"], marker='o', linestyle='-', color='b')
        plt.xlabel("Cumulative Volume (Million m³)")
        plt.ylabel("Level from Bottom")
        plt.title("Cumulative Volume vs Level")
        plt.grid(True)
        plt.savefig(chart_path)
        plt.close()

    def name(self):
        return "raster_depth_analysis_report"

    def displayName(self):
        return "Raster Depth Analysis Report"

    def createInstance(self):
        return RasterDepthAnalysis()

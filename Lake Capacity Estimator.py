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
    QgsProcessingParameterEnum, QgsProcessingParameterVectorLayer
)
from osgeo import gdal, ogr
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import csv

def clip_raster_with_vector(raster_path, vector_path, output_path):
    vector_ds = ogr.Open(vector_path)
    vector_layer = vector_ds.GetLayer()
    
    raster_ds = gdal.Open(raster_path)
    output_ds = gdal.Warp(output_path, raster_ds, cutlineDSName=vector_path, cropToCutline=True, dstNodata=-1)
    output_ds = None  # Save and close output
    return output_path

class RasterDepthAnalysis(QgsProcessingAlgorithm):
    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterEnum("RASTER_TYPE", "Raster Type", options=["Depth Raster", "Elevation Raster"], defaultValue=0))
        self.addParameter(QgsProcessingParameterRasterLayer("INPUT_RASTER", "Input Raster (Depth or Elevation) Value in Meters"))
        self.addParameter(QgsProcessingParameterVectorLayer("MASK_VECTOR", "Vector Mask Boundary (Optional)", optional=True))
        self.addParameter(QgsProcessingParameterEnum("OUTPUT_FORMAT", "Output Format", options=["CSV"], defaultValue=0))
        self.addParameter(QgsProcessingParameterFileDestination("OUTPUT_CSV_FILE", "Output CSV File", "CSV Files (*.csv)"))
        self.addParameter(QgsProcessingParameterBoolean("SKIP_OUTPUT", "Skip Output", defaultValue=False))
        self.addParameter(QgsProcessingParameterNumber("INCREMENT", "Depth Interval Increment", type=QgsProcessingParameterNumber.Double, minValue=0.01, defaultValue=0.1))
    
    def processAlgorithm(self, parameters, context, feedback):
        raster_type = self.parameterAsEnum(parameters, "RASTER_TYPE", context)
        raster_layer = self.parameterAsRasterLayer(parameters, "INPUT_RASTER", context)
        mask_vector = self.parameterAsVectorLayer(parameters, "MASK_VECTOR", context)
        output_csv_file = self.parameterAsFile(parameters, "OUTPUT_CSV_FILE", context)
        skip_output = self.parameterAsBoolean(parameters, "SKIP_OUTPUT", context)
        increment = self.parameterAsDouble(parameters, "INCREMENT", context)

        if not raster_layer or not raster_layer.isValid():
            raise ValueError("Invalid raster file")
        
        raster_path = raster_layer.source()
        clipped_raster_path = raster_path
        
        if mask_vector:
            clipped_raster_path = raster_path.replace('.tif', '_clipped.tif')
            clipped_raster_path = clip_raster_with_vector(raster_path, mask_vector.source(), clipped_raster_path)
        
        dataset = gdal.Open(clipped_raster_path)
        band = dataset.GetRasterBand(1)
        raster_array = band.ReadAsArray().astype(np.float32)
        
        no_data_value = band.GetNoDataValue()
        if no_data_value is not None:
            raster_array[raster_array == no_data_value] = np.nan
        
        if raster_type == 1:  # Elevation Raster
            min_elevation = np.nanmin(raster_array)
            max_value = np.nanmax(raster_array)
            max_extra = max_value + 0.0000001
            raster_array = max_extra - raster_array
        else:
            min_elevation = None
        
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

        first_depth_interval = depth_data[0][0]
        depth_data = [(str(depth), count, area, vol, cum_vol, float(first_depth_interval - depth))
                      for (depth, count, area), vol, cum_vol
                      in zip(depth_data, volume_data, cumulative_volume_data)]

        if raster_type == 1:
            depth_data = [(depth, count, area, vol, cum_vol, wl, wl + min_elevation)
                          for (depth, count, area, vol, cum_vol, wl) in depth_data]

        if skip_output:
            feedback.pushInfo(f"Pixel Size X: {pixel_size_x}")
            feedback.pushInfo(f"Pixel Size Y: {pixel_size_y}")
            feedback.pushInfo(f"Mean Resolution: {mean_resolution}")
            return {}

        chart_path = output_csv_file.replace('.csv', '_capacity.png')
        chart_path2 = output_csv_file.replace('.csv', '_area.png')
        self.generate_csv(output_csv_file, min_value, max_value, count_valid_pixels,
                          pixel_size_x, pixel_size_y, mean_resolution, depth_data, chart_path,chart_path2, raster_type)

        return {"OUTPUT_FILE": output_csv_file}

    def generate_csv(self, csv_path, min_val, max_val, pixel_count, pixel_size_x, pixel_size_y, mean_resolution, depth_data, chart_path,chart_path2, raster_type):
        if raster_type == 1:
            df = pd.DataFrame(depth_data, columns=[
                "Depth Interval", "Pixel Count", "Area (km²)",
                "Volume (Million m³)", "Cumulative Volume (Million m³)",
                "Water Level from Bottom", "Water Elevation from Bottom"
            ])
        else:
            df = pd.DataFrame(depth_data, columns=[
                "Depth Interval", "Pixel Count", "Area (km²)",
                "Volume (Million m³)", "Cumulative Volume (Million m³)",
                "Water Level from Bottom"
            ])

        self.generate_cumulative_volume_chart(chart_path, df, raster_type)
        df.loc[0, "Chart Path"] = chart_path
        self.generate_area_chart(chart_path2, df, raster_type)
        df.loc[1, "Chart Path"] = chart_path2
        df.to_csv(csv_path, index=False, quoting=csv.QUOTE_NONNUMERIC, float_format='%.6f')

    def generate_cumulative_volume_chart(self, chart_path, df, raster_type):
        plt.figure(figsize=(6, 4))
        y_label = "Water Elevation from Bottom" if raster_type == 1 else "Water Level from Bottom"
        y_data = "Water Elevation from Bottom" if raster_type == 1 else "Water Level from Bottom"
        plt.plot(df["Cumulative Volume (Million m³)"], df[y_data], marker='o', linestyle='-', color='b')
        plt.xlabel("Cumulative Volume (Million m³)")
        plt.ylabel(y_label)
        plt.title("Cumulative Volume vs " + y_label)
        plt.grid(True)
        plt.savefig(chart_path)
        plt.close()

    def generate_area_chart(self, chart_path2, df, raster_type):
        plt.figure(figsize=(6, 4))
        y_label = "Water Elevation from Bottom" if raster_type == 1 else "Water Level from Bottom"
        y_data = "Water Elevation from Bottom" if raster_type == 1 else "Water Level from Bottom"
        plt.plot(df["Area (km²)"], df[y_data], marker='o', linestyle='-', color='b')
        plt.xlabel("Area (km²)")
        plt.ylabel(y_label)
        plt.title("Area vs " + y_label)
        plt.grid(True)
        plt.savefig(chart_path2)
        plt.close()
    def name(self):
        return "raster_depth_analysis_report"

    def displayName(self):
        return "Raster Depth Analysis Report"

    def createInstance(self):
        return RasterDepthAnalysis()

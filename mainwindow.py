import configparser
import os
import random
from PyQt6 import QtWidgets, QtCore
from qt_material import apply_stylesheet
from grbl_streamer import GrblStreamer
import time
from dataclasses import asdict
import easy_biologic as ebl
import easy_biologic.base_programs as blp

import experiment
import fileio
from adlink import Adlink
from view.gridwidget import GridWidget
from view.robotwindow import RobotWindow
from view.setupwindow import SetupWindow

import csv
import matplotlib.pyplot as plt
from collections import namedtuple

DataSegment = namedtuple('DataSegment', ['data', 'info', 'values'])

def on_data_cb(segment, program):
    current = segment.values.get("Current (A)")
    time = segment.values.get("Time (s)")

    # Store data to CSV
    with open('data.csv', mode='a', newline='') as file:
        writer = csv.writer(file)
        writer.writerow([time, current])

    # Plotting the point
    plt.scatter(time, current)
    plt.xlabel('Time (s)')
    plt.ylabel('Current (A)')
    plt.title('Current vs Time')
    plt.draw()
    plt.pause(0.01)  # Pause to allow the plot to update

    plt.ion()  # Turn on interactive mode

def run_cv(bl, cv, index):
    params = asdict(cv)
    del params['name'] # Don't pass name to params

    CV = blp.CV(bl, params, channels=[4] ) # channel is to be claimed.

    # run program and save data into csv file.
    CV.run('data')
    #CV.on_data(on_data_cb)
    CV.save_data(f'CV{index}.csv')

def change_theme(theme):
    config = configparser.ConfigParser()
    config.read("config.ini")
    config.set('General', 'theme', theme)
    with open('config.ini', 'w') as configfile:
        config.write(configfile)
    apply_stylesheet(QtWidgets.QApplication.instance(), theme=theme)

def grbl_callback(eventstring, *data):
    args = []
    for d in data:
        args.append(str(d))
    print("GRBL CALLBACK: event={} data={}".format(eventstring.ljust(30), ", ".join(args)))

def init_adlink():
    adlink_card = Adlink()
    print("DEBUG MESSAGE: Adlink Card Initialized")
    return adlink_card

def init_par():
    kbio_port = config.get('Ports', 'vmp3_port')
    ec_lab = ebl.BiologicDevice(kbio_port)
    print("DEBUG MESSAGE: EC-Lab PAR Initialized")
    return ec_lab

def init_robot():
    grbl = GrblStreamer(grbl_callback)
    grbl.setup_logging()
    grbl_port = config.get('Ports', 'grbl_port')
    grbl.cnect(grbl_port, 115200)
    print("DEBUG MESSAGE: GRBL Connected")
    time.sleep(1)  # Let grbl connect
    grbl.killalarm()  # Turn off alarm on startup
    print("DEBUG MESSAGE: GRBL Alarm Turned off")
    return grbl

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, debug_window, enable_robot, enable_par):
        super().__init__()
        self.setWindowTitle("CombiMatrixAI")

        self.adlink_card = init_adlink()
        if enable_robot:
            self.grbl = init_robot()
        if enable_par:
            self.ec_lab = init_par()

        print("DEBUG MESSAGE: All Machines Initialized")

        self.blocks_dir = os.path.join(os.path.dirname(__file__), 'blocks')
        self.blocks = fileio.from_folder(self.blocks_dir, '.block')
        self.cv_dir = os.path.join(os.path.dirname(__file__), 'vcfgs', 'cv')
        self.cvs = fileio.from_folder(self.cv_dir, '.cv.vcfg')
        self.gcode_dir = os.path.join(os.path.dirname(__file__), 'gcode')
        self.gcode = fileio.from_folder(self.gcode_dir, '.gcode')

        self.setup_window = SetupWindow()
        self.setup_window.item_created.connect(self.item_created)

        if enable_robot:
            self.robot_window = RobotWindow(self.grbl)

        self.setup_button = QtWidgets.QPushButton("Setup", self)
        self.setup_button.clicked.connect(self.setup_window.show)
        self.debug_button = QtWidgets.QPushButton("Open Debug", self)
        self.debug_button.clicked.connect(debug_window.show)
        self.robot_controls_button = QtWidgets.QPushButton("Robot Controls", self)
        if enable_robot:
            self.robot_controls_button.clicked.connect(self.robot_window.show)
        self.chip_test_button = QtWidgets.QPushButton("Run Chip Test", self)
        self.chip_test_button.clicked.connect(lambda: self.chip_test(1))
        self.run_cv_button = QtWidgets.QPushButton("Run Experiments", self)
        self.run_cv_button.clicked.connect(lambda: self.run_experiments(enable_robot, enable_par))
        self.exit_button = QtWidgets.QPushButton("Exit", self)
        self.exit_button.clicked.connect(QtWidgets.QApplication.instance().quit)

        self.solution_input_label = QtWidgets.QLabel("Enter Solution:", self)
        self.solution_input = QtWidgets.QLineEdit(self)
        self.solution_input.setPlaceholderText("Solution")

        self.blocks_label = QtWidgets.QLabel("Load Block:", self)
        self.blocks_dropdown = QtWidgets.QComboBox(self)
        self.blocks_dropdown.addItems(list(self.blocks.keys()))
        self.tile_block_button = QtWidgets.QPushButton("Tile Block", self)
        self.tile_block_button.clicked.connect(lambda: self.tile_block())

        self.cvs_label = QtWidgets.QLabel("Load CV Config:", self)
        self.cvs_dropdown = QtWidgets.QComboBox(self)
        self.cvs_dropdown.addItems(list(self.cvs.keys()))

        self.gcode_label = QtWidgets.QLabel("Load G-code:", self)
        self.gcode_dropdown = QtWidgets.QComboBox(self)
        self.gcode_dropdown.addItems(list(self.gcode.keys()))
        self.execute_gcode_button = QtWidgets.QPushButton("Execute G-code", self)
        self.execute_gcode_button.clicked.connect(lambda: self.execute_gcode(self.experiments_list[self.curr_exp_index].gcode))

        self.save_experiment_button = QtWidgets.QPushButton("New Experiment", self)
        self.save_experiment_button.clicked.connect(self.save_experiment)
        self.update_experiment_button = QtWidgets.QPushButton("Update Experiment", self)
        self.update_experiment_button.clicked.connect(self.update_experiment)
        self.delete_experiment_button = QtWidgets.QPushButton("Delete Experiment", self)
        self.delete_experiment_button.clicked.connect(self.delete_experiment)

        self.grid_widget = GridWidget(5)

        self.curr_exp_index = 0
        # TODO: ADD COMPATIBILITY WITH NEW TECHNIQUES
        self.experiments_list = [experiment.Experiment("null", self.blocks[self.blocks_dropdown.currentText()],
                                            "CV",
                                            self.cvs[self.cvs_dropdown.currentText()],
                                            self.gcode[self.gcode_dropdown.currentText()])]
        self.load_block(self.blocks[self.blocks_dropdown.currentText()])


        self.experiments_tab = QtWidgets.QListWidget()
        self.experiments_tab.currentItemChanged.connect(self.exp_index_changed)
        self.experiments_tab.addItems([str(exp) for exp in self.experiments_list])
        self.experiments_tab.setFixedSize(700, 500)

        self.theme_label = QtWidgets.QLabel("Theme:", self)
        self.theme_dropdown = QtWidgets.QComboBox(self)
        self.theme_dropdown.addItems(
            ['dark_amber.xml', 'dark_blue.xml', 'dark_cyan.xml', 'dark_lightgreen.xml', 'dark_pink.xml',
             'dark_purple.xml', 'dark_red.xml', 'dark_teal.xml', 'dark_yellow.xml', 'light_amber.xml', 'light_blue.xml',
             'light_cyan.xml', 'light_cyan_500.xml', 'light_lightgreen.xml', 'light_pink.xml', 'light_purple.xml',
             'light_red.xml', 'light_teal.xml', 'light_yellow.xml'])
        self.theme_dropdown.activated.connect(lambda: change_theme(self.theme_dropdown.currentText()))
        self.version_label = QtWidgets.QLabel("CombiMatrixAI, App Version: 091224 Test", self)
        self.version_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignBottom | QtCore.Qt.AlignmentFlag.AlignRight)

        ############################### WINDOW LAYOUT #################################

        layout_master = QtWidgets.QVBoxLayout()

        layout_top = QtWidgets.QGridLayout()
        layout_top.addWidget(self.setup_button, 0, 0)
        layout_top.addWidget(self.debug_button, 0, 1)
        layout_top.addWidget(self.robot_controls_button, 0, 2)
        layout_top.addWidget(self.chip_test_button, 0, 3)
        layout_top.addWidget(self.run_cv_button, 0, 4)
        spacer_top = QtWidgets.QSpacerItem(100, 0, QtWidgets.QSizePolicy.Policy.Fixed,
                                       QtWidgets.QSizePolicy.Policy.Fixed)
        layout_top.addItem(spacer_top, 0, 5)
        layout_top.addWidget(self.exit_button, 0, 6)
        layout_master.addLayout(layout_top)

        layout_middle = QtWidgets.QHBoxLayout()
        layout_middle_grid = QtWidgets.QGridLayout()
        layout_middle_grid.addWidget(self.solution_input_label, 0, 0)
        layout_middle_grid.addWidget(self.solution_input, 0, 1, 1, 2)
        layout_middle_grid.addWidget(self.blocks_label, 1, 0)
        layout_middle_grid.addWidget(self.blocks_dropdown, 1, 1)
        layout_middle_grid.addWidget(self.tile_block_button, 1, 2)
        layout_middle_grid.addWidget(self.cvs_label, 2, 0)
        layout_middle_grid.addWidget(self.cvs_dropdown, 2, 1)
        layout_middle_grid.addWidget(self.gcode_label, 3, 0)
        layout_middle_grid.addWidget(self.gcode_dropdown, 3, 1)
        layout_middle_grid.addWidget(self.execute_gcode_button, 3, 2)
        layout_middle_grid.addWidget(self.save_experiment_button, 4, 0)
        layout_middle_grid.addWidget(self.update_experiment_button, 4, 1)
        layout_middle_grid.addWidget(self.delete_experiment_button, 4, 2)
        spacer = QtWidgets.QSpacerItem(125, 125, QtWidgets.QSizePolicy.Policy.Fixed,
                                       QtWidgets.QSizePolicy.Policy.Minimum)
        layout_middle_grid.addItem(spacer, 5, 0)
        layout_middle_grid.addItem(spacer, 5, 1)
        layout_middle.addLayout(layout_middle_grid)
        layout_middle.addWidget(self.experiments_tab)
        layout_middle.addWidget(self.grid_widget, 0,
                         QtCore.Qt.AlignmentFlag.AlignTop | QtCore.Qt.AlignmentFlag.AlignRight)  # Place the grid widget next to the other widgets
        layout_master.addLayout(layout_middle)

        layout_bottom = QtWidgets.QHBoxLayout()
        layout_bottom.addWidget(self.theme_label, 0, QtCore.Qt.AlignmentFlag.AlignLeft)
        layout_bottom.addWidget(self.theme_dropdown, 10, QtCore.Qt.AlignmentFlag.AlignLeft)
        layout_bottom.addWidget(self.version_label, 0,
                         QtCore.Qt.AlignmentFlag.AlignBottom | QtCore.Qt.AlignmentFlag.AlignRight)
        layout_master.addLayout(layout_bottom)

        container = QtWidgets.QWidget()
        container.setLayout(layout_master)
        self.setCentralWidget(container)

    def run_experiments(self, enable_robot, enable_par):
        index = 0
        for exp in self.experiments_list:
            if enable_robot:
                self.execute_gcode(exp.gcode)
            self.load_block(exp.block, True)
            if enable_par:
                run_cv(self.ec_lab, exp.vcfg, index)

            print("Experiment completed")
            index += 1

    def item_created(self, text):
        if text.split(',')[0].strip() == "Block Created":
            self.blocks = fileio.from_folder(self.blocks_dir, '.block')
            self.blocks_dropdown.clear()
            self.blocks_dropdown.addItems(list(self.blocks.keys()))
            new_index = self.blocks_dropdown.findText(text.split(',')[1].strip())
            self.blocks_dropdown.setCurrentIndex(new_index)
            self.load_block(self.blocks[self.blocks_dropdown.currentText()])
        elif text.split(',')[0].strip() == "CV Config Created":
            self.cvs = fileio.from_folder(self.cv_dir, '.cv.vcfg')
            self.cvs_dropdown.clear()
            self.cvs_dropdown.addItems(list(self.cvs.keys()))
            new_index = self.cvs_dropdown.findText(text.split(',')[1].strip())
            self.cvs_dropdown.setCurrentIndex(new_index)
            self.load_cv(self.cvs[self.cvs_dropdown.currentText()])

    def chip_test(self, channel):
        for i in range(7):
            match i:
                case 0:
                    chipmap_in = [[0] * 16 for _ in range(64)]
                case 1:
                    chipmap_in = [[1] * 16 for _ in range(64)]
                case 2:
                    chipmap_in = [[2] * 16 for _ in range(64)]
                case 3:
                    chipmap_in = [[3] * 16 for _ in range(64)]
                case 4:
                    chipmap_in = [[1 if (r + c) % 2 == 0 else 2 for c in range(16)] for r in range(64)]
                case 5:
                    chipmap_in = [[2 if (r + c) % 2 == 0 else 3 for c in range(16)] for r in range(64)]
                case 6:
                    chipmap_in = [[random.randint(0, 3) for _ in range(16)] for _ in range(64)]
                case _:
                    break

        self.adlink_card.set_chip_map(channel, chipmap_in)
        chipmap_out = self.adlink_card.get_chip_map(channel)

        for row in range(64):
            for column in range(16):
                self.grid_widget.set_square_color(row, column,
                                                      chipmap_in[row][column], chipmap_out[row][column])

        if chipmap_in == chipmap_out:
            print(f"Test {i} Passed")
        else:
            print(f"Test {i} Failed")
            differences = [
                (r, c, chipmap_in[r][c], chipmap_out[r][c])
                for r in range(len(chipmap_in))
                for c in range(len(chipmap_in[r]))
                if chipmap_in[r][c] != chipmap_out[r][c]
            ]
            for row, col, value1, value2 in differences:
                print(f"Row {row}, Col {col}: chipmap_in has {value1}, chipmap_out has {value2}")

    def execute_gcode(self, gcode):
        gcode_dir = os.path.join(os.path.dirname(__file__), 'gcode', gcode.file)
        self.grbl.load_file(gcode_dir)
        self.grbl.job_run()

    def tile_block(self):
        self.experiments_list[self.curr_exp_index].tile_block()

        block = self.experiments_list[self.curr_exp_index].block
        self.load_block(block)

    def update_exp_list(self):
        item = self.experiments_tab.item(self.curr_exp_index)
        if item:
            item.setText(str(self.experiments_list[self.curr_exp_index]))

    def load_block(self, block, set_card = False):
        # Logic for loading the block
        self.grid_widget.clear()
        current_map = [[0] * 16 for _ in range(64)]
        for i in range(block.num_rows):
            for j in range(block.num_cols):
                current_map[block.start_row + i][block.start_col + j] = block.definition[i][j]
                self.grid_widget.set_square_color(block.start_row + i, block.start_col + j,
                                                  current_map[block.start_row + i][block.start_col + j])
        if set_card:
            self.adlink_card.set_chip_map(1, current_map)

    def exp_index_changed(self, i): # Not an index, i is a QListWidgetItem
        print(f"Row changed to {self.experiments_tab.row(i)}")
        self.curr_exp_index = self.experiments_tab.row(i)
        if self.curr_exp_index != -1: # Dont load anything if list is empty
            self.load_block(self.experiments_list[self.curr_exp_index].block)
            index = self.blocks_dropdown.findText(self.experiments_list[self.curr_exp_index].block.name)
            self.blocks_dropdown.setCurrentIndex(index)
            index = self.cvs_dropdown.findText(self.experiments_list[self.curr_exp_index].vcfg.name)
            self.cvs_dropdown.setCurrentIndex(index)
            index = self.gcode_dropdown.findText(self.experiments_list[self.curr_exp_index].gcode.name)
            self.gcode_dropdown.setCurrentIndex(index)

    def save_experiment(self):
        # TODO: ADD COMPATIBILITY WITH NEW TECHNIQUES
        self.experiments_list.append(
            experiment.Experiment(self.solution_input.text(), self.blocks[self.blocks_dropdown.currentText()], "CV",
                                                self.cvs[self.cvs_dropdown.currentText()], self.gcode[self.gcode_dropdown.currentText()]))
        self.experiments_tab.addItem(str(self.experiments_list[-1]))

    def update_experiment(self):
        # TODO: ADD COMPATIBILITY WITH NEW TECHNIQUES
        self.experiments_list[self.curr_exp_index] = experiment.Experiment(self.solution_input.text(),
                                                                           self.blocks[self.blocks_dropdown.currentText()],
                                                                           "CV",
                                                                            self.cvs[self.cvs_dropdown.currentText()],
                                                                           self.gcode[self.gcode_dropdown.currentText()])
        self.load_block(self.experiments_list[self.curr_exp_index].block)
        item = self.experiments_tab.item(self.curr_exp_index)
        if item:
            item.setText(str(self.experiments_list[self.curr_exp_index]))

    def delete_experiment(self):
        if self.curr_exp_index == -1:
            return
        del self.experiments_list[self.curr_exp_index]
        self.experiments_tab.clear()
        self.experiments_tab.addItems([str(exp) for exp in self.experiments_list])

# How to run

For running the commands as -
`
factory < input.json > output.json
`
`
belts < input.json > output.json
`

follow the below steps (my machine is **ubuntu 24.04** , so catered to that),
assuming you are in **"part2_assignment"** 

## Make both python files exectuable first
`
chmod 755 ./factory/main.py
`
`
chmod 755 ./belts/main.py
`

## Transfer the files to /usr/local/bin and rename as stated
`
sudo mv ./factory/main.py /usr/local/bin/factory
`
`
sudo mv ./belts/main.py /usr/local/bin/belts
`


Now you can directly run the commands, given input.json is present in the directory where you run the command. 

# NOTE
**#!/usr/bin/env python3** is added at the top of python file to tell linux how to execute the file.
So make sure you have python3 present

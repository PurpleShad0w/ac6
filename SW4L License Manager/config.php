<?php
$config = parse_ini_file('config.ini');
$conn = mysqli_connect($config['dbhost'], $config['username'], $config['password']);
mysqli_select_db($conn, $config['db']);
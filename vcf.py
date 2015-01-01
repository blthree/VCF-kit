from subprocess import PIPE, Popen, call
from collections import OrderedDict
from tabulate import tabulate as tb
from datetime import datetime
from utils import *
import numpy as np
import shlex
import re
import sys
import csv

standard_set_names = ["CHROM", "POS", "REF", "ALT", "QUAL", "FILTER"]
standard_set = [OrderedDict([("id","CHROM"), ("desc", "Chromosome"), ("type", "String")]),
    OrderedDict([("id","POS"), ("desc", "Position"), ("type", "Integer")]),
    OrderedDict([("id","REF"), ("desc", "Reference Allele"), ("type", "String")]),
    OrderedDict([("id","ALT"), ("desc", "Alternate Allele"), ("type", "String")]),
    OrderedDict([("id","QUAL"), ("desc", "Variant Quality"), ("type", "Float")]),
    OrderedDict([("id","FILTER"), ("desc", "Filter"), ("type", "String")])]

standard_set_types = {"CHROM":"String",
                      "POS":"Integer",
                      "REF":"String",
                      "ALT":"String",
                      "QUAL":"Float",
                      "FILTER":"String"}



class vcf:
  def __init__(self, filename):
      # Start by storing basic information about the vcf/bcf and checking that an index exists.
      self.filename = filename
      self.analysis_dir = replace_all(self.filename,[".bcf", ".vcf",".gz"], "").strip(".")
      make_dir(self.analysis_dir)
      self.header = command(["bcftools","view","-h",filename])
      # Samples
      self.samples = command(["bcftools","query","-l",filename]).split("\n")

      # Meta Data
      self.metadata = OrderedDict(re.compile(r'''^##(?P<key>[^<#]+?)=(?P<val>[^<#]+$)''', re.M).findall(self.header))

      # Contigs
      self.contigs = [x.split(",") for x in re.compile(r'''^##contig=<(?P<data>.*)>''', re.M).findall(self.header)]
      self.contigs = [dict([(x.split("=")[0],set_type(x.split("=")[1])) for x in f]) for f in self.contigs]
      self.contigs = dict([(x["ID"],x) for x in self.contigs])
      
      # Info
      r = re.compile(r'''\#\#INFO=<
          ID=(?P<id>[^,]+),
          Number=(?P<number>-?\d+|\.|[AG]),
          Type=(?P<type>Integer|Float|Flag|Character|String),
          Description="(?P<desc>[^"]*)"
          >''', re.VERBOSE)
      self.info_set = {x["id"]:x for x in [m.groupdict() for m in r.finditer(self.header)]}
      
      # Filter
      r = re.compile(r'''\#\#FILTER=<
          ID=(?P<id>[^,]+),
          Description="(?P<desc>[^"]*)"
          >''', re.VERBOSE)
      self.filter_set = {x["id"]:x for x in [m.groupdict() for m in r.finditer(self.header)]}
      
      # Format
      r = re.compile(r'''\#\#FORMAT=<
          ID=(?P<id>.+),
          Number=(?P<number>-?\d+|\.|[AG]),
          Type=(?P<type>.+),
          Description="(?P<desc>.*)"
          >''', re.VERBOSE)
      self.format_set = {x["id"]:x for x in [m.groupdict() for m in r.finditer(self.header)]}
      self.info_format_variables = self.info_set.keys() + self.format_set.keys()
      self.complete_var_list = standard_set_names + self.info_format_variables


  def list_vars(self):
    # Resolve Variable Specification Issues
    print("")
    print(bc("STANDARD","BOLD"))
    print tb(standard_set, headers="keys", tablefmt="grid")
    print("")
    print(bc("INFO FIELDS","BOLD"))
    info = [OrderedDict([("id","INFO/" + x["id"]), ("desc", x["desc"]), ("type", x["type"])]) for x in self.info_set.values()]
    print tb(info, headers="keys", tablefmt="grid")
    print("")
    print(bc("FORMAT FIELDS","BOLD"))
    format = [OrderedDict([("id", "FORMAT/" + x["id"]), ("desc", x["desc"]), ("type", x["type"])]) for x in self.format_set.values()]
    print tb(format, headers="keys", tablefmt="grid")
    print("")
    print("""Variables have been prefixed with "INFO/" or "FORMAT/", \nhowever these prefixes are not necessary if the variable \nis unique within both groups.
        """)


  def resolve_variable(self, var):
    """ Returns proper specification of variable,
    variable name for plotting, and split variables
    as needed.
    """
    if var == None:
        return {"query": None, "df": None , "type": None}
    var = var.replace("%", "")
    search_var = var.replace("FORMAT/", "").replace("INFO/","")
    if search_var not in self.complete_var_list:
        error("%s not found; Use listvars to see available variables" % var)
    elif self.info_format_variables.count(var) > 1:
        error("%s is defined in FORMAT and INFO sets; prefix with INFO/ or FORMAT/" % var)
    elif var.startswith("INFO/") and var.replace("INFO/", "") not in self.info_set.keys():
        error("%s not found in INFO variables" % var)
    elif var in standard_set_names:
        return {"query":"%" + var, "include": var.replace("INFO/", ""), "df": var, "type": standard_set_types[var], "number": 1}
    else:
        include_rep = var # Used with --include
        if var.startswith("INFO/") or var in self.info_set.keys():
            var_info = self.info_set[var.replace("INFO/","")]
            var_number = int(var_info["number"])
            if var_number > 1:
                var_data_rep =  ','.join([var + "." + str(v) for v in range(0,int(var_number))])
            else:
                var_data_rep = var
            var_data_rep = var_data_rep.replace("/", ".").replace("%","")
            if var.startswith("INFO/"):
                query_string = "%" + var
            else:
                query_string = "%INFO/" + var
            return {"query": query_string, "include": include_rep,"df": var_data_rep , "type": var_info["type"], "number": var_number}
        else:
            var_info = self.format_set[var.replace("FORMAT/","")]
            var_number = int(var_info["number"])
            if var_number > 1:
                var_data_rep =  ','.join([var + "." + str(v) for v in range(0,int(var_number))])
            else:
                var_data_rep = var
            var_data_rep = var_data_rep.replace("/", ".").replace("%","")
            query_string = "[%" + var.replace("FORMAT/","") + "\\n]"
            return {"query": query_string, "include": include_rep, "df": var_data_rep , "type": var_info["type"], "number": var_number}
  
  def format_data_file_name(self,filename, x = None,y = None):
    filename = replace_all(filename,["bcf", "vcf","gz"], "").strip(".")
    if x == None:
        x = ""
    if y == None:
        y = ""
    x, y  = replace_all(x, ["%","[","\n]","]"], ""), replace_all(y, ["%","[","\n","]"], "")
    x, y  = x.replace("/", "-"), y.replace("/", "-")
    if y != "":
        y = "." + y
    return "{filename}.{x}{y}".format(**locals())

  def query(self, x, y = None, region = None, include = None):
    # Create analysis directory
    
    x = self.resolve_variable(x)
    y = self.resolve_variable(y)

    # Get dataframe rep to create header.
    if y["df"] == None:
        header = x["df"] + "\n"
    else:
        header = x["df"] + "," + y["df"] + "\n"

    # Set up Query Variables
    if y["query"] == None:
        variables = x["query"] + "\n"
    else:
        variables = x["query"] + "," + y["query"] + "\n"

    # If position is being queried, add chromosome
    if variables.find("%POS") == 0:
        header = "CHROM," + header
        variables = "%CHROM," + variables

    # Region option
    if region != "":
      region = "--regions " + region 


    q = shlex.split("bcftools query -f \"{variables}\" {region} {filename}".format(variables=variables, region=region, filename=self.filename))
    filename = self.format_data_file_name(self.filename, x["query"],y["query"])
    filename_pre = self.analysis_dir + "/" + filename
    remove_file(filename_pre)
    with open(filename_pre + ".txt","w+") as out:
        out.write(header)
        for line in Popen(q, stdout=PIPE).stdout:
            if line.strip() != "":
                out.write(line)

    if y["query"] == None:
        return self.analysis_dir, filename, x
    else:
        return self.analysis_dir, filename, x, y

  def compare_vcf(self, variable = None, pairs = None, vcf2 = None):
    """ Analyzes concordance of samples """

    filename_pre = self.analysis_dir + "/" + self.format_data_file_name("Concordance_" + self.filename, variable )
    remove_file(filename_pre)
    #[2]Discordance  [3]Number of sites  [4]Average minimum depth  [5]Sample i [6]Sample j
    base_header = ["Discordant_Sites", "Number_of_Sites", "Average_minimum_depth", "Sample_i", "Sample_j", "Same_Sample", "Concordance"]

    # Test for variables that are not allowed.
    if variable in ["CHROM"]:
      error("%s not allowed for variant comparisons" % variable)

    if pairs is not None:
      pairs = [tuple(sorted(x.split(","))) for x in pairs.split(":")]

    if vcf2 is not None:
      # Merge vcfs here and sort out variable names later.
      pass

    elif variable is None:
      # Simple heat map
      concordance_results = command(["bcftools", "gtcheck", "-G", "1", self.filename])
      # [(1.0 - x[0]*1.0/x[1])] Concordance is added as the last column
      concordance_results = [x.split("\t")[1:] + [1.0 - float(x[1])/float(x[2])] for x in concordance_results.split("\n") if x.startswith("CN")]
      # Output here, simple heatmap plot.
    else:
      #
      # Assess concordance across a variable.
      #
      variable = self.resolve_variable(variable)
      q = "bcftools query -f '{variable}\\n' {filename}".format(variable=variable["query"], filename=self.filename)
      var_data = sorted(map(set_type,set(np.array(command(q, shell=True).strip().split("\n")))))
      # Bin data as needed
      binning = False
      if len(var_data) > 100:
        # Use quantiles
        var_data = [np.percentile(var_data, x) for x in range(0,100,1)]
        binning = True
        print bc("More than 100 different values for %s, binning by percentile" % variable["include"], "BOLD")
      with open(filename_pre + ".txt","w+") as f:
        # Setup file, write header.
        fn = base_header + [variable["df"]]
        out = csv.DictWriter(f, delimiter='\t', fieldnames=fn)
        out.writerow(dict((fn,fn) for fn in out.fieldnames))

        for i in var_data:
          print("Comparing Genotypes at {var}={i};\t ({index}/{total})".format(var=variable["include"],i=i, index=var_data.index(i)+1, total=len(var_data)))
          if i != '':
            if type(i) == str:
              irep = i
              i = '"' + i + '"'
            else:
              irep = i
            if binning == True:
              if var_data.index(i) == 0:
                lower_bound = 0
              else:
                lower_bound = var_data[var_data.index(i) - 1]
              include_string = "{variable}>={lower_bound} && {variable}<{upper_bound}".format(variable=variable["include"], lower_bound = lower_bound, upper_bound = i)
            else:
              include_string = "{variable}=={i}".format(variable=variable["include"], i=i)
            q = "bcftools view --include '{include_string}' {filename} | bcftools gtcheck -G 1 - ".format(include_string=include_string, filename=self.filename)
            # cr = concordance results
            cr = command(q, shell=True)
            # Filter for concordance values
            cr = [map(set_type,x.split("\t")[1:]) for x in cr.split("\n") if x.startswith("CN")]
            # Insert concordance rate
            for k,v in enumerate(cr):
              cr_dict = {}
              cr_dict["Discordant_Sites"] = v[0]
              cr_dict["Average_minimum_depth"] = v[1]
              cr_dict["Sample_i"] = v[2]
              cr_dict["Sample_j"] = v[3]
              cr_dict["Same_Sample"] = v[0]
              cr_dict[variable["df"]] = i
              # Insert if they are the same sample.
              if tuple(sorted([v[3],v[4]])) in pairs:
                cr_dict["Same_Sample"] = 1
              else:
                cr_dict["Same_Sample"] = 0
              #Insert concordance rate.
              if cr[k][1] != 0:
                 cr_dict["Concordance"] = 1-v[0]/float(v[1])
              else:
                 cr_dict["Concordance"] = 0
              out.writerow(cr_dict)
        

  def _parse_stats(lines):
    stats = {}
    values_lines = []
    lines = lines.split("\n")
    for l in lines:
      if l.startswith("#"):
        if len(values_lines) > 0:
          stats[stat_section] = values_lines
          values_lines = []
        parse_header = re.sub("\[[0-9]+\]","",l.replace("# ","")).split("\t")
        stat_section = parse_header[0]
        columns = parse_header[1:]
      else:
        formatted_values = coerce_types(l.split("\t"))[1:]
        values_lines.append(zip(columns,formatted_values))
    return stats